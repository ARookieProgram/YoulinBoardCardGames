import * as db from "../utils/db";

import type { RoomRow } from "../types/db_rows";
import type { GameManager, RoomConf, RoomCreateConf, RoomInfo, RoomSeat } from "../types/domain";

/**
 * 房间内存表 + 按 `conf.type` 选择玩法实现。
 *
 * 三件事必须一起看：
 * 1. 房间与座位（`rooms` / `userLocation`）只是内存表，落库靠 `utils/db.ts`；
 * 2. 玩法实现（gamemgr_xlch / gamemgr_xzdd）**按需懒加载**——两个模块末尾都有
 *    `setInterval(update,1000)`，同时加载会跑起两个定时器；
 * 3. `userLocation` 是"玩家在哪个房间哪个座位"的唯一来源，`usermgr` 广播时也查它。
 */

/** 玩家在房间里的位置。 */
interface UserLocation {
  roomId: string;
  seatIndex: number;
}

/** 建房结果回调：errcode 0 成功并带回房间号，其它取值见 createRoom。 */
export type CreateRoomCallback = (errcode: number, roomId: string | null) => void;

/** 进房结果回调：0 正常，1 房间已满，2 找不到房间。 */
export type EnterRoomCallback = (ret: number) => void;

var rooms: Record<string, RoomInfo | undefined> = {};
var creatingRooms: Record<string, true | undefined> = {};

var userLocation: Record<number, UserLocation | undefined> = {};
var totalRooms = 0;

var DI_FEN = [1,2,5];
var MAX_FAN = [3,4,5];
var JU_SHU = [4,8];
var JU_SHU_COST = [2,3];

/**
 * 生成 6 位房间号。
 *
 * @returns 房间号字符串。
 */
function generateRoomId(): string {
	var roomId = "";
	for(var i = 0; i < 6; ++i){
		roomId += Math.floor(Math.random()*10);
	}
	return roomId;
}

/**
 * 按玩法类型懒加载 gamemgr 实现。
 *
 * **必须懒加载**：两个 gamemgr 文件末尾都 `setInterval(update,1000)`，顶层同时 require 会跑起
 * 两个定时器。原实现把 require 写在函数体里，这里保持同样的时机，只把结果标注成 `GameManager`。
 *
 * @param type 房间的 `conf.type`；非 "xlch" 一律用 xzdd（与原实现一致）。
 * @returns 玩法实现模块。
 */
function loadGameManager(type: string): GameManager {
	// 动态 require 的模块路径无法静态解析，所以这里是一次断言。两份实现各自在文件末尾
	// 做了一次 `const _contract: GameManager = {...}` 的编译期自检，断言因此是有依据的。
	return require(type == "xlch" ? "./gamemgr_xlch" : "./gamemgr_xzdd") as GameManager;
}

/**
 * 用 `t_rooms` 里的一行还原房间（进程重启后玩家回来时走这条路）。
 *
 * @param dbdata 房间行。
 * @returns 还原出来的房间。
 */
function constructRoomFromDb(dbdata: RoomRow): RoomInfo {
	var conf: RoomConf = JSON.parse(dbdata.base_info);
	var roomInfo: RoomInfo = {
		uuid:dbdata.uuid,
		id:dbdata.id,
		numOfGames:dbdata.num_of_turns,
		createTime:dbdata.create_time,
		nextButton:dbdata.next_button,
		seats:new Array<RoomSeat>(4),
		conf:conf,
		gameMgr:loadGameManager(conf.type)
	};


	var roomId = roomInfo.id;

	// 原实现是按 "user_id" + i 这类字段名拼出来的动态取值；这里显式列出四列，
	// 读的是同一批列、同样的下标，行为不变。
	var userIds = [dbdata.user_id0, dbdata.user_id1, dbdata.user_id2, dbdata.user_id3];
	var scores = [dbdata.user_score0, dbdata.user_score1, dbdata.user_score2, dbdata.user_score3];
	var names = [dbdata.user_name0, dbdata.user_name1, dbdata.user_name2, dbdata.user_name3];

	for(var i = 0; i < 4; ++i){
		// 座位对象逐个字段赋值（原实现如此）；`{} as RoomSeat` 是一次断言，
		// 好处是下面每一行都被 RoomSeat 约束住，而运行时仍然从空对象开始。
		var s = roomInfo.seats[i] = {} as RoomSeat;
		s.userId = userIds[i];
		s.score = scores[i];
		s.name = names[i];
		s.ready = false;
		s.seatIndex = i;
		s.numZiMo = 0;
		s.numJiePao = 0;
		s.numDianPao = 0;
		s.numAnGang = 0;
		s.numMingGang = 0;
		s.numChaJiao = 0;

		if(s.userId > 0){
			userLocation[s.userId] = {
				roomId:roomId,
				seatIndex:i
			};
		}
	}
	rooms[roomId] = roomInfo;
	totalRooms++;
	return roomInfo;
}

/**
 * 建房：校验入参、生成房间号、写库，成功后回调带回房间号。
 *
 * 校验的边界条件（包括 `> 长度` 这种差一位的写法）与错误码都保持原样：
 * 1 参数非法、2222 房卡不足、3 写库失败。
 *
 * @param creator 房主 userId。
 * @param roomConf 建房入参。
 * @param gems 房主的房卡数。
 * @param ip 房间所在 ip。
 * @param port 房间所在端口。
 * @param callback 结果回调。
 */
export function createRoom(creator: number, roomConf: RoomCreateConf, gems: number, ip: string, port: number, callback: CreateRoomCallback): void {
	if(
		roomConf.type == null
		|| roomConf.difen == null
		|| roomConf.zimo == null
		|| roomConf.jiangdui == null
		|| roomConf.huansanzhang == null
		|| roomConf.zuidafanshu == null
		|| roomConf.jushuxuanze == null
		|| roomConf.dianganghua == null
		|| roomConf.menqing == null
		|| roomConf.tiandihu == null){
		callback(1,null);
		return;
	}

	if(roomConf.difen < 0 || roomConf.difen > DI_FEN.length){
		callback(1,null);
		return;
	}

	if(roomConf.zimo < 0 || roomConf.zimo > 2){
		callback(1,null);
		return;
	}

	if(roomConf.zuidafanshu < 0 || roomConf.zuidafanshu > MAX_FAN.length){
		callback(1,null);
		return;
	}

	if(roomConf.jushuxuanze < 0 || roomConf.jushuxuanze > JU_SHU.length){
		callback(1,null);
		return;
	}

	var cost = JU_SHU_COST[roomConf.jushuxuanze];
	if(cost > gems){
		callback(2222,null);
		return;
	}

	// 自引用闭包必须显式标注类型（否则 TS 无法推断）。
	var fnCreate: () => void = function(){
		var roomId = generateRoomId();
		if(rooms[roomId] != null || creatingRooms[roomId] != null){
			fnCreate();
		}
		else{
			creatingRooms[roomId] = true;
			db.is_room_exist(roomId, function(ret) {

				if(ret){
					delete creatingRooms[roomId];
					fnCreate();
				}
				else{
					var createTime = Math.ceil(Date.now()/1000);
					var roomInfo: RoomInfo = {
						uuid:"",
						id:roomId,
						numOfGames:0,
						createTime:createTime,
						nextButton:0,
						seats:[],
						conf:{
							// 断言说明：入参的 type 没有白名单校验，原实现按 "xlch" / 其它 二分，
							// 并把原字符串落库。这里同样原样落库，只把类型标注成 RoomType。
							type:roomConf.type as RoomConf["type"],
							baseScore:DI_FEN[roomConf.difen],
						    zimo:roomConf.zimo,
						    jiangdui:roomConf.jiangdui,
						    hsz:roomConf.huansanzhang,
						    dianganghua:parseInt(String(roomConf.dianganghua)),
						    menqing:roomConf.menqing,
						    tiandihu:roomConf.tiandihu,
						    maxFan:MAX_FAN[roomConf.zuidafanshu],
						    maxGames:JU_SHU[roomConf.jushuxuanze],
						    creator:creator,
						},
						gameMgr:loadGameManager(roomConf.type)
					};

					console.log(roomInfo.conf);

					for(var i = 0; i < 4; ++i){
						roomInfo.seats.push({
							userId:0,
							score:0,
							name:"",
							ready:false,
							seatIndex:i,
							numZiMo:0,
							numJiePao:0,
							numDianPao:0,
							numAnGang:0,
							numMingGang:0,
							numChaJiao:0,
						});
					}


					//写入数据库
					var conf = roomInfo.conf;
					db.create_room(roomInfo.id,roomInfo.conf,ip,port,createTime,function(uuid){
						delete creatingRooms[roomId];
						if(uuid != null){
							roomInfo.uuid = uuid;
							console.log(uuid);
							rooms[roomId] = roomInfo;
							totalRooms++;
							callback(0,roomId);
						}
						else{
							callback(3,null);
						}
					});
				}
			});
		}
	}

	fnCreate();
}

/**
 * 销毁房间：清掉座位上的玩家位置、删内存表与库里的记录。
 *
 * @param roomId 房间号。
 */
export function destroy(roomId: string): void {
	var roomInfo = rooms[roomId];
	if(roomInfo == null){
		return;
	}

	for(var i = 0; i < 4; ++i){
		var userId = roomInfo.seats[i].userId;
		if(userId > 0){
			delete userLocation[userId];
			db.set_room_id_of_user(userId,null);
		}
	}

	delete rooms[roomId];
	totalRooms--;
	db.delete_room(roomId);
}

/**
 * 当前房间总数（心跳上报用）。
 *
 * @returns 房间数。
 */
export function getTotalRooms(): number {
	return totalRooms;
}

/**
 * 取房间。
 *
 * @param roomId 房间号。
 * @returns 房间；不存在则 undefined。
 */
export function getRoom(roomId: string): RoomInfo | undefined {
	return rooms[roomId];
};

/**
 * 判断是不是房主。
 *
 * 注意签名：第二个参数可选，因为 `socket_service` 里有一处历史调用只传了一个
 * 参数（实际传进去的是 userId），此时 `rooms[userId]` 取不到房间、返回 false。
 * 保留这个行为，不要改成"补齐参数"。
 *
 * @param roomId 房间号（历史调用点传的是 userId）。
 * @param userId 玩家 id。
 * @returns 是房主为 true。
 */
export function isCreator(roomId: string | number, userId?: number): boolean {
	var roomInfo = rooms[roomId];
	if(roomInfo == null){
		return false;
	}
	return roomInfo.conf.creator == userId;
};

/**
 * 进房：占用一个空座位；内存里没有房间时先从库里还原。
 *
 * @param roomId 房间号。
 * @param userId 玩家 id。
 * @param userName 玩家昵称。
 * @param callback 结果回调（0 正常 / 1 房间已满 / 2 找不到房间）。
 */
export function enterRoom(roomId: string, userId: number, userName: string, callback: EnterRoomCallback): void {
	var fnTakeSeat: (room: RoomInfo) => number = function(room){
		if(getUserRoom(userId) == roomId){
			//已存在
			return 0;
		}

		for(var i = 0; i < 4; ++i){
			var seat = room.seats[i];
			if(seat.userId <= 0){
				seat.userId = userId;
				seat.name = userName;
				userLocation[userId] = {
					roomId:roomId,
					seatIndex:i
				};
				//console.log(userLocation[userId]);
				db.update_seat_info(roomId,i,seat.userId,"",seat.name);
				//正常
				return 0;
			}
		}
		//房间已满
		return 1;
	}
	var room = rooms[roomId];
	if(room){
		var ret = fnTakeSeat(room);
		callback(ret);
	}
	else{
		db.get_room_data(roomId,function(dbdata){
			if(dbdata == null){
				//找不到房间
				callback(2);
			}
			else{
				//construct room.
				room = constructRoomFromDb(dbdata);
				//
				var ret = fnTakeSeat(room);
				callback(ret);
			}
		});
	}
};

/**
 * 设置座位准备状态。
 *
 * @param userId 玩家 id。
 * @param value 是否已准备。
 */
export function setReady(userId: number, value: boolean): void {
	var roomId = getUserRoom(userId);
	if(roomId == null){
		return;
	}

	var room = getRoom(roomId);
	if(room == null){
		return;
	}

	var seatIndex = getUserSeat(userId);
	if(seatIndex == null){
		return;
	}

	var s = room.seats[seatIndex];
	s.ready = value;
}

/**
 * 取座位准备状态。
 *
 * @param userId 玩家 id。
 * @returns 未进房时 undefined。
 */
export function isReady(userId: number): boolean | undefined {
	var roomId = getUserRoom(userId);
	if(roomId == null){
		return;
	}

	var room = getRoom(roomId);
	if(room == null){
		return;
	}

	var seatIndex = getUserSeat(userId);
	if(seatIndex == null){
		return;
	}

	var s = room.seats[seatIndex];
	return s.ready;
}


/**
 * 取玩家所在房间。
 *
 * @param userId 玩家 id。
 * @returns 房间号；不在房间时为 null。
 */
export function getUserRoom(userId: number): string | null {
	var location = userLocation[userId];
	if(location != null){
		return location.roomId;
	}
	return null;
};

/**
 * 取玩家所在座位。
 *
 * @param userId 玩家 id。
 * @returns 座位号；不在房间时为 null。
 */
export function getUserSeat(userId: number): number | null {
	var location = userLocation[userId];
	//console.log(userLocation[userId]);
	if(location != null){
		return location.seatIndex;
	}
	return null;
};

/**
 * 取"玩家 -> 位置"整张表（`/get_server_info` 内部接口用）。
 *
 * @returns 位置表本身（不是副本，与原实现一致）。
 */
export function getUserLocations(): Record<number, UserLocation | undefined> {
	return userLocation;
};

/**
 * 退出房间：清座位、清位置；房间空了就销毁。
 *
 * @param userId 玩家 id。
 */
export function exitRoom(userId: number): void {
	var location = userLocation[userId];
	if(location == null)
		return;

	var roomId = location.roomId;
	var seatIndex = location.seatIndex;
	var room = rooms[roomId];
	delete userLocation[userId];
	if(room == null || seatIndex == null) {
		return;
	}

	var seat = room.seats[seatIndex];
	seat.userId = 0;
	seat.name = "";

	var numOfPlayers = 0;
	for(var i = 0; i < room.seats.length; ++i){
		if(room.seats[i].userId > 0){
			numOfPlayers++;
		}
	}

	db.set_room_id_of_user(userId,null);

	if(numOfPlayers == 0){
		destroy(roomId);
	}
};
