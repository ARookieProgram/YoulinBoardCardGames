"""房间内存表 + 按 `conf.type` 选择玩法实现。

对应 `server/game_server/roommgr.ts`。三件事必须一起看：

1. 房间与座位（`rooms` / `user_location`）只是内存表，落库靠 `utils/db.py`；
2. 玩法实现（`gamemgr_xlch` / `gamemgr_xzdd`）**按需懒加载**——两个模块在 import 时都会
   起一个每秒跑一次的 `update()` 任务，同时加载会跑起两个定时器；
3. `user_location` 是"玩家在哪个房间哪个座位"的唯一来源，`usermgr` 广播时也查它。

与 Node 版的差异：需要碰数据库的几个函数（`create_room` / `enter_room` / `destroy` /
`exit_room`）改为**协程 + 返回值**，不再用回调；`create_room` 返回 `(errcode, roomId)`，
`enter_room` 直接返回 errcode。
"""

from __future__ import annotations

import importlib
import json
import math
import random
import time
from dataclasses import dataclass
from typing import Any

from shared.domain import (
    GameManagerProtocol,
    RoomConf,
    RoomInfo,
    RoomSeat,
    RoomType,
)
from utils import db

from game_server import robotmgr


@dataclass
class UserLocation:
    """玩家在房间里的位置。"""

    roomId: str
    seatIndex: int


rooms: dict[str, RoomInfo] = {}
creating_rooms: dict[str, bool] = {}

user_location: dict[int, UserLocation] = {}
_total_rooms = 0

DI_FEN = [1, 2, 5]
MAX_FAN = [3, 4, 5]
JU_SHU = [4, 8]
JU_SHU_COST = [2, 3]


def generate_room_id() -> str:
    """生成 6 位房间号。"""
    room_id = ""
    for _ in range(6):
        room_id += str(math.floor(random.random() * 10))
    return room_id


def load_game_manager(type_: str) -> GameManagerProtocol:
    """按玩法类型懒加载 gamemgr 实现。

    **必须懒加载**：两个 gamemgr 模块 import 时都会起一个每秒跑一次的定时器，
    顶层同时 import 会跑起两个。原实现把 `require` 写在函数体里，这里保持同样的时机。

    :param type_: 房间的 `conf.type`；非 "xlch" 一律用 xzdd（与原实现一致）。
    """
    module = "game_server.gamemgr_xlch" if type_ == "xlch" else "game_server.gamemgr_xzdd"
    return importlib.import_module(module)


def room_conf_from_dict(data: dict[str, Any]) -> RoomConf:
    """把库里 `base_info` 的 JSON 还原成 `RoomConf`。"""
    return RoomConf(
        type=data.get("type", "xlch"),
        baseScore=data.get("baseScore", 0),
        zimo=data.get("zimo", 0),
        jiangdui=data.get("jiangdui", 0),
        hsz=data.get("hsz", 0),
        dianganghua=data.get("dianganghua", 0),
        menqing=data.get("menqing", 0),
        tiandihu=data.get("tiandihu", 0),
        maxFan=data.get("maxFan", 0),
        maxGames=data.get("maxGames", 0),
        creator=data.get("creator", 0),
        # 单人模式开关。正常单人房是新建后立刻打完的，`base_info` 里并没有写它
        # （`utils/db._conf_to_wire` 的键集与 Node 版保持一致，见那里的注释），
        # 这里读取只为向前兼容：万一以后把它落库了，还原出来的房间仍然认得自己是单人房。
        single=data.get("single", 0),
    )


def construct_room_from_db(dbdata: dict[str, Any]) -> RoomInfo:
    """用 `t_rooms` 里的一行还原房间（进程重启后玩家回来时走这条路）。"""
    conf = room_conf_from_dict(json.loads(dbdata["base_info"]))
    room_info = RoomInfo(
        uuid=dbdata["uuid"],
        id=dbdata["id"],
        numOfGames=dbdata["num_of_turns"],
        createTime=dbdata["create_time"],
        nextButton=dbdata["next_button"],
        seats=[],
        conf=conf,
        gameMgr=load_game_manager(conf.type),
    )

    room_id = room_info.id
    user_ids = [dbdata["user_id0"], dbdata["user_id1"], dbdata["user_id2"], dbdata["user_id3"]]
    scores = [dbdata["user_score0"], dbdata["user_score1"], dbdata["user_score2"], dbdata["user_score3"]]
    names = [dbdata["user_name0"], dbdata["user_name1"], dbdata["user_name2"], dbdata["user_name3"]]

    for i in range(4):
        seat = RoomSeat(
            userId=user_ids[i],
            score=scores[i],
            name=names[i],
            ready=False,
            seatIndex=i,
            numZiMo=0,
            numJiePao=0,
            numDianPao=0,
            numAnGang=0,
            numMingGang=0,
            numChaJiao=0,
        )
        room_info.seats.append(seat)

        if seat.userId > 0:
            user_location[seat.userId] = UserLocation(roomId=room_id, seatIndex=i)

    global _total_rooms
    rooms[room_id] = room_info
    _total_rooms += 1
    return room_info


async def _seat_robots(room_info: RoomInfo) -> None:
    """单人模式：把三个机器人安排到 1~3 号座位。

    它们和真人座位的**唯一区别是没有 socket**：

    * 写 `user_location`，这样 `get_user_room` / `get_user_seat`（广播、结算都查它）照常可用；
    * `robotmgr.register` 标记身份，`usermgr.is_online` 据此对它们恒返回 True，
      `gamemgr.set_ready` 的"四人齐"判断才能通过、牌局才开得起来；
    * `ready=True`，真人登录时 `set_ready` 一进来就能开局，不需要额外的准备流程；
    * `db.update_seat_info` 与真人落座走同一条路，`t_rooms` 里的座位信息保持一致。

    机器人的 userId 由 `robotmgr.allocate_ids` 从 900000 起分配，不会和 `t_users` 的自增主键撞号。
    """
    robot_ids = robotmgr.allocate_ids(3)
    for offset, robot_id in enumerate(robot_ids):
        seat_index = offset + 1
        if seat_index >= len(room_info.seats):
            break
        seat = room_info.seats[seat_index]
        seat.userId = robot_id
        seat.name = robotmgr.robot_name(offset)
        seat.ready = True
        robotmgr.register(robot_id)
        user_location[robot_id] = UserLocation(roomId=room_info.id, seatIndex=seat_index)
        await db.update_seat_info(room_info.id, seat_index, robot_id, "", seat.name)


async def create_room(
    creator: int,
    room_conf: dict[str, Any],
    gems: float,
    ip: str,
    port: int,
) -> tuple[int, str | None]:
    """建房：校验入参、生成房间号、写库。

    校验的边界条件（包括 `> 长度` 这种差一位的写法）与错误码都保持原样：
    1 参数非法、2222 房卡不足、3 写库失败。

    :return: `(errcode, roomId)`；成功时 errcode 为 0。
    """
    if (
        room_conf.get("type") is None
        or room_conf.get("difen") is None
        or room_conf.get("zimo") is None
        or room_conf.get("jiangdui") is None
        or room_conf.get("huansanzhang") is None
        or room_conf.get("zuidafanshu") is None
        or room_conf.get("jushuxuanze") is None
        or room_conf.get("dianganghua") is None
        or room_conf.get("menqing") is None
        or room_conf.get("tiandihu") is None
    ):
        return 1, None

    if room_conf["difen"] < 0 or room_conf["difen"] > len(DI_FEN):
        return 1, None

    if room_conf["zimo"] < 0 or room_conf["zimo"] > 2:
        return 1, None

    if room_conf["zuidafanshu"] < 0 or room_conf["zuidafanshu"] > len(MAX_FAN):
        return 1, None

    if room_conf["jushuxuanze"] < 0 or room_conf["jushuxuanze"] > len(JU_SHU):
        return 1, None

    # 注意：索引可能越界（`> len` 而不是 `>= len`），越界时取值会抛异常——与原实现一致。
    cost = JU_SHU_COST[room_conf["jushuxuanze"]]
    # 单人模式（人机）不扣房卡：真人一个人打，也拿不到别人出的房卡钱，
    # 所以跳过"房卡够不够"的校验（房间每次开局时的扣费同样跳过，见 gamemgr 的 do_game_over）。
    is_single = room_conf.get("single") is not None and room_conf.get("single") != 0
    if not is_single and cost > gems:
        return 2222, None

    async def fn_create() -> tuple[int, str | None]:
        room_id = generate_room_id()
        if rooms.get(room_id) is not None or creating_rooms.get(room_id) is not None:
            return await fn_create()

        creating_rooms[room_id] = True
        if await db.is_room_exist(room_id):
            del creating_rooms[room_id]
            return await fn_create()

        create_time = math.ceil(time.time() * 1000 / 1000)
        room_info = RoomInfo(
            uuid="",
            id=room_id,
            numOfGames=0,
            createTime=create_time,
            nextButton=0,
            seats=[],
            conf=RoomConf(
                # 入参的 type 没有白名单校验，原实现按 "xlch" / 其它 二分并把原字符串落库。
                type=room_conf["type"],
                baseScore=DI_FEN[room_conf["difen"]],
                zimo=room_conf["zimo"],
                jiangdui=room_conf["jiangdui"],
                hsz=room_conf["huansanzhang"],
                dianganghua=int(str(room_conf["dianganghua"])),
                menqing=room_conf["menqing"],
                tiandihu=room_conf["tiandihu"],
                maxFan=MAX_FAN[room_conf["zuidafanshu"]],
                maxGames=JU_SHU[room_conf["jushuxuanze"]],
                creator=creator,
                single=1 if is_single else 0,
            ),
            gameMgr=load_game_manager(room_conf["type"]),
        )

        print(_conf_to_wire(room_info.conf))

        for i in range(4):
            room_info.seats.append(
                RoomSeat(
                    userId=0,
                    score=0,
                    name="",
                    ready=False,
                    seatIndex=i,
                    numZiMo=0,
                    numJiePao=0,
                    numDianPao=0,
                    numAnGang=0,
                    numMingGang=0,
                    numChaJiao=0,
                )
            )

        # 写入数据库
        uuid = await db.create_room(room_info.id, room_info.conf, ip, port, create_time)
        creating_rooms.pop(room_id, None)
        if uuid is not None:
            global _total_rooms
            room_info.uuid = uuid
            print(uuid)
            rooms[room_id] = room_info
            _total_rooms += 1
            if is_single:
                # 单人模式：先把 1~3 号座位发给机器人，0 号位留给建房者，
                # 这样大厅服随后调 `/enter_room` 时真人会自然坐到 0 号位。
                await _seat_robots(room_info)
            return 0, room_id
        return 3, None

    return await fn_create()


async def destroy(room_id: str) -> None:
    """销毁房间：清掉座位上的玩家位置、删内存表与库里的记录。"""
    room_info = rooms.get(room_id)
    if room_info is None:
        return

    global _total_rooms
    for i in range(4):
        user_id = room_info.seats[i].userId
        if user_id > 0:
            user_location.pop(user_id, None)
            await db.set_room_id_of_user(user_id, None)

    del rooms[room_id]
    _total_rooms -= 1
    await db.delete_room(room_id)


def get_total_rooms() -> int:
    """当前房间总数（心跳上报用）。"""
    return _total_rooms


def get_room(room_id: str) -> RoomInfo | None:
    """取房间；不存在则 None。"""
    return rooms.get(room_id)


def is_creator(room_id: str | int, user_id: int | None = None) -> bool:
    """判断是不是房主。

    注意签名：第二个参数可选，因为 `socket_service` 里有一处历史调用只传了一个参数
    （实际传进去的是 userId），此时 `rooms[userId]` 取不到房间、返回 False。
    保留这个行为，不要改成"补齐参数"。
    """
    room_info = rooms.get(room_id)  # type: ignore[arg-type]
    if room_info is None:
        return False
    return room_info.conf.creator == user_id


async def enter_room(room_id: str, user_id: int, user_name: str) -> int:
    """进房：占用一个空座位；内存里没有房间时先从库里还原。

    :return: 0 正常 / 1 房间已满 / 2 找不到房间。
    """

    async def fn_take_seat(room: RoomInfo) -> int:
        if get_user_room(user_id) == room_id:
            # 已存在
            return 0

        for i in range(4):
            seat = room.seats[i]
            if seat.userId <= 0:
                seat.userId = user_id
                seat.name = user_name
                user_location[user_id] = UserLocation(roomId=room_id, seatIndex=i)
                await db.update_seat_info(room_id, i, seat.userId, "", seat.name)
                # 正常
                return 0
        # 房间已满
        return 1

    room = rooms.get(room_id)
    if room is not None:
        return await fn_take_seat(room)

    dbdata = await db.get_room_data(room_id)
    if dbdata is None:
        # 找不到房间
        return 2
    room = construct_room_from_db(dbdata)
    return await fn_take_seat(room)


def set_ready(user_id: int, value: bool) -> None:
    """设置座位准备状态。"""
    room_id = get_user_room(user_id)
    if room_id is None:
        return
    room = get_room(room_id)
    if room is None:
        return
    seat_index = get_user_seat(user_id)
    if seat_index is None:
        return
    room.seats[seat_index].ready = value


def is_ready(user_id: int) -> bool | None:
    """取座位准备状态；未进房时 None。"""
    room_id = get_user_room(user_id)
    if room_id is None:
        return None
    room = get_room(room_id)
    if room is None:
        return None
    seat_index = get_user_seat(user_id)
    if seat_index is None:
        return None
    return room.seats[seat_index].ready


def get_user_room(user_id: int) -> str | None:
    """取玩家所在房间；不在房间时为 None。"""
    location = user_location.get(user_id)
    if location is not None:
        return location.roomId
    return None


def get_user_seat(user_id: int) -> int | None:
    """取玩家所在座位；不在房间时为 None。"""
    location = user_location.get(user_id)
    if location is not None:
        return location.seatIndex
    return None


def get_user_locations() -> dict[int, UserLocation]:
    """取"玩家 -> 位置"整张表（`/get_server_info` 内部接口用）。返回的是表本身，不是副本。"""
    return user_location


async def exit_room(user_id: int) -> None:
    """退出房间：清座位、清位置；房间空了就销毁。"""
    location = user_location.get(user_id)
    if location is None:
        return

    room_id = location.roomId
    seat_index = location.seatIndex
    room = rooms.get(room_id)
    user_location.pop(user_id, None)
    if room is None:
        return

    seat = room.seats[seat_index]
    seat.userId = 0
    seat.name = ""

    num_of_players = 0
    for s in room.seats:
        if s.userId > 0:
            num_of_players += 1

    await db.set_room_id_of_user(user_id, None)

    if num_of_players == 0:
        await destroy(room_id)


def reset() -> None:
    """清空内存表（只给测试用；Node 版没有这个函数，它靠进程重启）。"""
    global _total_rooms
    rooms.clear()
    creating_rooms.clear()
    user_location.clear()
    _total_rooms = 0


def _conf_to_wire(conf: RoomConf) -> dict[str, Any]:
    """与 `JSON.stringify(conf)` 键序一致的字典，只用于日志打印。"""
    return {
        "type": conf.type,
        "baseScore": conf.baseScore,
        "zimo": conf.zimo,
        "jiangdui": conf.jiangdui,
        "hsz": conf.hsz,
        "dianganghua": conf.dianganghua,
        "menqing": conf.menqing,
        "tiandihu": conf.tiandihu,
        "maxFan": conf.maxFan,
        "maxGames": conf.maxGames,
        "creator": conf.creator,
    }


__all__ = [
    "RoomType",
    "construct_room_from_db",
    "create_room",
    "destroy",
    "enter_room",
    "exit_room",
    "generate_room_id",
    "get_room",
    "get_total_rooms",
    "get_user_locations",
    "get_user_room",
    "get_user_seat",
    "is_creator",
    "is_ready",
    "load_game_manager",
    "reset",
    "room_conf_from_dict",
    "rooms",
    "set_ready",
    "user_location",
]
