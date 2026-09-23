"""游戏域模型：房间 / 座位 / 单局对局状态。

对应 `server/types/domain.ts`。命名对应关系：

    RoomInfo   房间（`roommgr.rooms[roomId]`）
    RoomSeat   房间里的座位（`roomInfo.seats[i]`），管的是玩家与分数
    GameState  一局对局（gamemgr 里的 `game`）
    GameSeat   对局里的座位（`game.gameSeats[i]`），管的是手牌与操作

两种对象的建模方式不同，这是本移植里最需要解释的一件事：

* **结构性对象**（上面四个）用 `dataclass`：字段固定、需要可读性，写错字段名要立刻报错。
* **上线载荷 / JS 式动态对象**（`huInfo` 的元素、`actions` 的记录、各种 push 的载荷）
  一律用**普通 dict**。原因是 Node 版的 `JSON.stringify` 会**丢掉值为 `undefined` 的键**，
  而 `null` 会被保留；`dataclass` 会把所有字段都序列化出去，形状就对不上了。
  用 dict 才能逐字复现"哪些键出现、哪些键不出现"。

`TingPaiInfo` 是唯一既有结构又会动态补字段的：`findMaxFanTingPai` 会往命中的那条上补
`pai`。它不参与序列化，所以用 dataclass。
"""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

# ---------------------------------------------------------------------------
# 基础别名
# ---------------------------------------------------------------------------

RoomType = Literal["xlch", "xzdd"]

#: `game.state` 的全部取值。
GamePhase = Literal["idle", "huanpai", "dingque", "playing", "nop"]

#: 手牌计数表：牌 id -> 张数（空间换时间，用于快速判定碰/杠）。
CountMap = dict[int, int]

#: `huInfo` 的元素。字段按 gamemgr 里实际写入的形状，用 dict 才能忠实复现
#: "值为 undefined 的键不出现"这一 JSON 行为。
HuInfoItem = dict[str, Any]

#: `recordUserAction` 写入 `GameSeat.actions` 的单条记录（同样是 dict，理由同上）。
UserActionRecord = dict[str, Any]


@dataclass
class TingPaiInfo:
    """听牌表里的一条：牌型与番数（`findMaxFanTingPai` 会补 `pai`）。"""

    pattern: str = ""
    fan: int = 0
    #: 只有 `findMaxFanTingPai` 命中时才会被赋值；不参与序列化。
    pai: int = -1


#: 听牌表：牌 id -> 该牌的和牌信息。
TingMap = dict[int, TingPaiInfo]


@dataclass
class RoomConf:
    """落库的房间配置（`t_rooms.base_info`，对局逻辑只认这一层）。"""

    type: RoomType = "xlch"
    baseScore: int = 1
    zimo: int = 0
    jiangdui: int = 0
    #: 换三张开关，由入参 `huansanzhang` 映射而来。
    hsz: int = 0
    dianganghua: int = 0
    menqing: int = 0
    tiandihu: int = 0
    maxFan: int = 3
    maxGames: int = 4
    #: 房主 userId。
    creator: int = 0
    #: 单人模式（人机）开关：1 表示建房时自动补三个机器人、不扣房卡。
    #: 只有 `/create_single_room` 会带上它，普通房间恒为 0。
    single: int = 0


@dataclass
class RoomSeat:
    """房间里的一个座位：玩家身份、分数与该玩家的累计统计。"""

    userId: int = 0
    score: int = 0
    name: str = ""
    ready: bool = False
    seatIndex: int = 0
    numZiMo: int = 0
    numJiePao: int = 0
    numDianPao: int = 0
    numAnGang: int = 0
    numMingGang: int = 0
    numChaJiao: int = 0
    #: 登录握手时由 `socket_service` 写入（socket.io 的对端地址）。
    ip: str | None = None


@dataclass
class DissolveRequest:
    """解散申请（`roomInfo.dr`，由 `dissolveRequest` 写入、`update()` 每秒检查超时）。"""

    #: 毫秒时间戳，超过它就算解散失败。
    endTime: int = 0
    #: 四个座位的同意状态。
    states: list[bool] = field(default_factory=lambda: [False, False, False, False])


@dataclass
class QiangGangContext:
    """抢杠上下文（`game.qiangGangContext`）。"""

    turnSeat: "GameSeat | None" = None
    seatData: "GameSeat | None" = None
    pai: int = -1
    isValid: bool = False


@dataclass
class GameState:
    """一局对局。"""

    conf: RoomConf = field(default_factory=RoomConf)
    roomInfo: "RoomInfo | None" = None
    gameIndex: int = 0
    button: int = 0
    #: 洗好的牌墙，108 张。
    mahjongs: list[int] = field(default_factory=list)
    currentIndex: int = 0
    gameSeats: list["GameSeat"] = field(default_factory=list)
    numOfQue: int = 0
    turn: int = 0
    #: 最近打出的牌。
    chuPai: int = -1
    state: GamePhase = "idle"
    #: 第一张胡的牌（-1 表示无）。
    firstHupai: int = -1
    yipaoduoxiang: int = -1
    fangpaoshumu: int = -1
    #: 操作流水，按 `si, action, pai` 依次 push，故为扁平数组。
    actionList: list[int] = field(default_factory=list)
    #: 胡牌顺序（xzdd 专属）：`hu` 里 push 座位号，结算时用 `indexOf` 得出 `huorder`。
    hupaiList: list[int] = field(default_factory=list)
    chupaiCnt: int = 0
    lastHuPaiSeat: int = -1
    qiangGangContext: QiangGangContext | None = None
    #: 换三张用的换牌方式（0 对家 / 1 下家 / 2 上家），写入后不再被读。
    huanpaiMethod: int = 0
    #: 一局的基础信息 JSON，`construct_game_base_info` 写入、`store_game` 落库。
    baseInfoJson: str = ""

    # 说明：Node 版的 `GameState` 上还有一个**从未被写入**的 `lastFangGangSeat`
    # （只有 `GameSeat.lastFangGangSeat` 会被写）。`hu()` 里读它做
    # `(undefined - game.turn + 4) % 4`，结果恒为 NaN，比较恒为 false。
    # 这里不建这个字段，改为在 `hu()` 里直接写出"该分支恒不成立"的结论并加注释，
    # 语义完全一致（见 game_server/gamemgr_*.py 的 `hu`）。


@dataclass
class GameSeat:
    """对局里的一个座位：手牌、副露、可执行操作与统计。"""

    game: GameState | None = None
    seatIndex: int = 0
    userId: int = 0
    #: 手牌。
    holds: list[int] = field(default_factory=list)
    #: 打出的牌。
    folds: list[int] = field(default_factory=list)
    #: 暗杠的牌。
    angangs: list[int] = field(default_factory=list)
    #: 点杠的牌。
    diangangs: list[int] = field(default_factory=list)
    #: 弯杠（碰后补杠）的牌。
    wangangs: list[int] = field(default_factory=list)
    #: 碰了的牌。
    pengs: list[int] = field(default_factory=list)
    #: 定缺花色，-1 表示未定。
    que: int = -1
    #: 换三张换来的牌，未换时为 None。
    huanpais: list[int] | None = None
    countMap: CountMap = field(default_factory=dict)
    tingMap: TingMap = field(default_factory=dict)
    pattern: str = ""
    canGang: bool = False
    #: 可以杠的牌。
    gangPai: list[int] = field(default_factory=list)
    canPeng: bool = False
    canHu: bool = False
    canChuPai: bool = False
    #: >=0 表示处于过胡状态：只能胡大于该番数的牌。
    guoHuFan: int = -1
    hued: bool = False
    actions: list[UserActionRecord] = field(default_factory=list)
    iszimo: bool = False
    isGangHu: bool = False
    fan: int = 0
    score: int = 0
    huInfo: list[HuInfoItem] = field(default_factory=list)
    lastFangGangSeat: int = -1
    numZiMo: int = 0
    numJiePao: int = 0
    numDianPao: int = 0
    numAnGang: int = 0
    numMingGang: int = 0
    numChaJiao: int = 0
    #: 结算时算出来的清一色标记（`calculateResult` 写入）。
    qingyise: bool = False
    #: 结算时算出来的门清标记（房间开 `menqing` 时才写）。
    isMenQing: bool = False
    #: 结算时算出来的金钩胡标记（手上只剩 1~2 张）。
    isJinGouHu: bool = False
    #: 结算时算出来的中张标记（房间开 `menqing` 时才写）。
    isZhongZhang: bool = False
    #: 结算时算出来的根数（xzdd 独有；xlch 用局部函数 `getNumOfGen`，不往座位上写）。
    numofgen: int = 0
    #: 杠上炮胡标记（xzdd 独有，`hu` 里写）。
    isQiangGangHu: bool = False
    #: 海底胡标记（xzdd 独有，`hu` 里写）。
    isHaiDiHu: bool = False
    #: 天胡标记（xzdd 独有，房间开 `tiandihu` 时才可能写）。
    isTianHu: bool = False
    #: 地胡标记（xzdd 独有，房间开 `tiandihu` 时才可能写）。
    isDiHu: bool = False


@dataclass
class RoomInfo:
    """房间。"""

    #: `t_rooms.uuid`，建房前为空字符串。
    uuid: str = ""
    #: 6 位房间号。
    id: str = ""
    numOfGames: int = 0
    #: 秒级时间戳。
    createTime: int = 0
    nextButton: int = 0
    seats: list[RoomSeat] = field(default_factory=list)
    conf: RoomConf = field(default_factory=RoomConf)
    #: 玩法实现（gamemgr_xlch / gamemgr_xzdd），按 `conf.type` 懒加载。
    gameMgr: Any = None
    #: 解散申请，仅在解散流程中被写入。
    dr: DissolveRequest | None = None


class GameManagerProtocol(Protocol):
    """两份玩法实现共同满足的契约（对应 Node 版的 `types/domain.ts` 的 `GameManager`）。

    `roommgr` 按房间类型懒加载其中一份（不能同时加载：两个模块 import 时都会起一个
    每秒跑一次的定时器），所以这里用 `Protocol` 把"gamemgr 必须提供什么"固定下来，
    两份实现在各自文件末尾做一次自检。

    注意 `set_ready` 的第二个参数：原实现的签名里有 `callback?`，但**没有任何调用点传它**，
    保留是为了让签名与 Node 版对得上。
    """

    async def set_ready(self, user_id: int, callback: Any = None) -> None: ...

    async def begin(self, room_id: str) -> None: ...

    async def huan_san_zhang(self, user_id: int, p1: int, p2: int, p3: int) -> None: ...

    async def ding_que(self, user_id: int, type: int) -> None: ...

    async def chu_pai(self, user_id: int, pai: int) -> None: ...

    async def peng(self, user_id: int) -> None: ...

    def is_playing(self, user_id: int) -> bool: ...

    async def gang(self, user_id: int, pai: int) -> None: ...

    async def hu(self, user_id: int) -> None: ...

    async def guo(self, user_id: int) -> None: ...

    def has_began(self, room_id: str) -> bool: ...

    async def do_dissolve(self, room_id: str) -> None: ...

    def dissolve_request(self, room_id: str, user_id: int) -> RoomInfo | None: ...

    def dissolve_agree(self, room_id: str, user_id: int, agree: bool) -> RoomInfo | None: ...
