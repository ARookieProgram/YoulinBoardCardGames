import * as nodeHttp from "node:http";

import express from "express";
import socketio from "socket.io";

import * as crypto from "../utils/crypto";
import * as db from "../utils/db";
import * as http from "../utils/http";
import * as roomMgr from "./roommgr";
import * as tokenMgr from "./tokenmgr";
import * as userMgr from "./usermgr";

import type { Request, Response, NextFunction } from "express";
import type { RawServer, RawSocket } from "socket.io";
import type { GameServerConfig } from "../types/config";
import type { GameSocket } from "../types/protocol";

/**
 * 对局协议的唯一入口：所有 `socket.on(...)` 都在这里。
 *
 * 登录链路（见 server/AGENTS.md §3）：
 * 客户端拿大厅服给的一次性 token 连上来，`login` 里校验
 * `md5(roomid + token + time + ROOM_PRI_KEY)` 与 token 时效，然后登记连接、取房间与座位，
 * 把 `socket.gameMgr` 指向该房间的玩法实现；之后所有业务动作都走 `socket.gameMgr.xxx(...)`。
 *
 * 推送：对局内一律走 `userMgr`；只有登录/连接阶段的 7 处直接 `socket.emit`
 * （`login_result`×4、`login_finished`、`exit_result`、`game_pong`）是例外。
 */

/**
 * `login` 事件的入参：客户端发来的是一个 JSON 字符串，这里自己 parse。
 * 字段全部按"可能缺失"处理，因为校验就在下面几行。
 */
interface LoginPayload {
  token?: string;
  roomid?: string;
  time?: string | number;
  sign?: string;
}

/** 换三张事件的入参（对象形态）。 */
interface HuanPaiPayload {
  p1?: number;
  p2?: number;
  p3?: number;
}

/** 登录成功回包里每个座位的结构（字段名就是写给客户端的那套，保持小写）。 */
interface SeatPushInfo {
  userid: number;
  ip?: string;
  score: number;
  name: string;
  online: boolean;
  ready: boolean;
  seatindex: number;
}

var io: RawServer | null = null;

var app = express();

//设置跨域访问
app.all('*', function(req: Request, res: Response, next: NextFunction) {
    res.header("Access-Control-Allow-Origin", "*");
    res.header("Access-Control-Allow-Headers", "X-Requested-With");
    res.header("Access-Control-Allow-Methods","PUT,POST,GET,DELETE,OPTIONS");
    res.header("X-Powered-By",' 3.2.1')
    res.header("Content-Type", "application/json;charset=utf-8");
	http.send(res,0,"ok",{});
});

var config: GameServerConfig | null = null;

/**
 * 启动游戏服：建 HTTP 服务、挂 socket.io、监听客户端端口。
 *
 * @param conf 游戏服配置。
 * @param mgr 原实现的第二个参数从未使用，保留以维持调用点一致。
 * @returns 该进程的 http.Server（交给 app.ts 汇总成启动横幅）。
 */
export function start(conf: GameServerConfig, mgr?: unknown): nodeHttp.Server {
	config = conf;

	var httpServer = nodeHttp.createServer(app);
	io = socketio(httpServer);
	httpServer.listen(config.CLIENT_PORT);

	// socket.io 1.x 不自带类型，连接对象的类型是 types/socket.io.d.ts 里的最小声明。
	// 这里是全仓唯一一次断言：把它接上本仓库的 GameSocket（带事件名与载荷类型），
	// 之后所有处理器都受协议类型约束。
	io.sockets.on('connection',function(rawSocket: RawSocket){
		var socket = rawSocket as unknown as GameSocket;
		socket.on('login',function(data){
			var loginData: LoginPayload = JSON.parse(data);
			if(socket.userId != null){
				//已经登陆过的就忽略
				return;
			}
			var token = loginData.token;
			var loginRoomId = loginData.roomid;
			var time = loginData.time;
			var sign = loginData.sign;

			console.log(loginRoomId);
			console.log(token);
			console.log(time);
			console.log(sign);


			//检查参数合法性
			if(token == null || loginRoomId == null || sign == null || time == null){
				console.log(1);
				socket.emit('login_result',{errcode:1,errmsg:"invalid parameters"});
				return;
			}

			//检查参数是否被篡改
			var md5 = crypto.md5(loginRoomId + token + time + config!.ROOM_PRI_KEY);
			if(md5 != sign){
				console.log(2);
				socket.emit('login_result',{errcode:2,errmsg:"login failed. invalid sign!"});
				return;
			}

			//检查token是否有效
			if(tokenMgr.isTokenValid(token)==false){
				console.log(3);
				socket.emit('login_result',{errcode:3,errmsg:"token out of time."});
				return;
			}

			//检查房间合法性
			var userId = tokenMgr.getUserID(token);
			var roomId = roomMgr.getUserRoom(userId);

			userMgr.bind(userId,socket);
			socket.userId = userId;

			//返回房间信息
			// 说明：原实现同样不判空（roomId 或座位为空时这里会抛 TypeError），
			// 断言只是把类型对齐，运行时行为不变；要加保护请单独开一次改动。
			var roomInfo = roomMgr.getRoom(roomId!)!;

			var seatIndex = roomMgr.getUserSeat(userId);
			roomInfo.seats[seatIndex!].ip = socket.handshake.address;

			var userData: SeatPushInfo | null = null;
			var seats: SeatPushInfo[] = [];
			for(var i = 0; i < roomInfo.seats.length; ++i){
				var rs = roomInfo.seats[i];
				var online = false;
				if(rs.userId > 0){
					online = userMgr.isOnline(rs.userId);
				}

				seats.push({
					userid:rs.userId,
					ip:rs.ip,
					score:rs.score,
					name:rs.name,
					online:online,
					ready:rs.ready,
					seatindex:i
				});

				if(userId == rs.userId){
					userData = seats[i];
				}
			}

			//通知前端
			var ret = {
				errcode:0,
				errmsg:"ok",
				data:{
					roomid:roomInfo.id,
					conf:roomInfo.conf,
					numofgames:roomInfo.numOfGames,
					seats:seats
				}
			};
			socket.emit('login_result',ret);

			//通知其它客户端
			userMgr.broacastInRoom('new_user_comes_push',userData,userId);

			socket.gameMgr = roomInfo.gameMgr;

			//玩家上线，强制设置为TRUE
			socket.gameMgr.setReady(userId);

			socket.emit('login_finished');

			if(roomInfo.dr != null){
				var dr = roomInfo.dr;
				var ramaingTime = (dr.endTime - Date.now()) / 1000;
				var noticeData = {
					time:ramaingTime,
					states:dr.states
				}
				userMgr.sendMsg(userId,'dissolve_notice_push',noticeData);
			}
		});

		socket.on('ready',function(data){
			var userId = socket.userId;
			if(userId == null){
				return;
			}
			socket.gameMgr.setReady(userId);
			userMgr.broacastInRoom('user_ready_push',{userid:userId,ready:true},userId,true);
		});

		//换牌
		socket.on('huanpai',function(data){
			if(socket.userId == null){
				return;
			}
			if(data == null){
				return;
			}

			var huanpai: HuanPaiPayload = typeof(data) == "string" ? JSON.parse(data) : data;

			var p1 = huanpai.p1;
			var p2 = huanpai.p2;
			var p3 = huanpai.p3;
			if(p1 == null || p2 == null || p3 == null){
				console.log("invalid data");
				return;
			}
			socket.gameMgr.huanSanZhang(socket.userId,p1,p2,p3);
		});

		//定缺
		socket.on('dingque',function(data){
			if(socket.userId == null){
				return;
			}
			var que = data;
			socket.gameMgr.dingQue(socket.userId,que);
		});

		//出牌
		socket.on('chupai',function(data){
			if(socket.userId == null){
				return;
			}
			var pai = data;
			socket.gameMgr.chuPai(socket.userId,pai);
		});

		//碰
		socket.on('peng',function(data){
			if(socket.userId == null){
				return;
			}
			socket.gameMgr.peng(socket.userId);
		});

		//杠
		socket.on('gang',function(data){
			if(socket.userId == null || data == null){
				return;
			}
			var pai = -1;
			if(typeof(data) == "number"){
				pai = data;
			}
			else if(typeof(data) == "string"){
				pai = parseInt(data);
			}
			else{
				console.log("gang:invalid param");
				return;
			}
			socket.gameMgr.gang(socket.userId,pai);
		});

		//胡
		socket.on('hu',function(data){
			if(socket.userId == null){
				return;
			}
			socket.gameMgr.hu(socket.userId);
		});

		//过  遇上胡，碰，杠的时候，可以选择过
		socket.on('guo',function(data){
			if(socket.userId == null){
				return;
			}
			socket.gameMgr.guo(socket.userId);
		});

		//聊天
		socket.on('chat',function(data){
			if(socket.userId == null){
				return;
			}
			var chatContent = data;
			userMgr.broacastInRoom('chat_push',{sender:socket.userId,content:chatContent},socket.userId,true);
		});

		//快速聊天
		socket.on('quick_chat',function(data){
			if(socket.userId == null){
				return;
			}
			var chatId = data;
			userMgr.broacastInRoom('quick_chat_push',{sender:socket.userId,content:chatId},socket.userId,true);
		});

		//语音聊天
		socket.on('voice_msg',function(data){
			if(socket.userId == null){
				return;
			}
			console.log(data.length);
			userMgr.broacastInRoom('voice_msg_push',{sender:socket.userId,content:data},socket.userId,true);
		});

		//表情
		socket.on('emoji',function(data){
			if(socket.userId == null){
				return;
			}
			var phizId = data;
			userMgr.broacastInRoom('emoji_push',{sender:socket.userId,content:phizId},socket.userId,true);
		});

		//语音使用SDK不出现在这里

		//退出房间
		socket.on('exit',function(data){
			var userId = socket.userId;
			if(userId == null){
				return;
			}

			var roomId = roomMgr.getUserRoom(userId);
			if(roomId == null){
				return;
			}

			//如果游戏已经开始，则不可以
			if(socket.gameMgr.hasBegan(roomId)){
				return;
			}

			//如果是房主，则只能走解散房间
			// 说明：这里历史上只传了一个参数（传进去的其实是 userId），
			// roommgr.isCreator 因此取不到房间、恒返回 false——保留该行为。
			if(roomMgr.isCreator(userId)){
				return;
			}

			//通知其它玩家，有人退出了房间
			userMgr.broacastInRoom('exit_notify_push',userId,userId,false);

			roomMgr.exitRoom(userId);
			userMgr.del(userId);

			socket.emit('exit_result');
			socket.disconnect();
		});

		//解散房间
		socket.on('dispress',function(data){
			var userId = socket.userId;
			if(userId == null){
				return;
			}

			var roomId = roomMgr.getUserRoom(userId);
			if(roomId == null){
				return;
			}

			//如果游戏已经开始，则不可以
			if(socket.gameMgr.hasBegan(roomId)){
				return;
			}

			//如果不是房主，则不能解散房间
			if(roomMgr.isCreator(roomId,userId) == false){
				return;
			}

			userMgr.broacastInRoom('dispress_push',{},userId,true);
			userMgr.kickAllInRoom(roomId);
			roomMgr.destroy(roomId);
			socket.disconnect();
		});

		//解散房间
		socket.on('dissolve_request',function(data){
			var userId = socket.userId;
			console.log(1);
			if(userId == null){
				console.log(2);
				return;
			}

			var roomId = roomMgr.getUserRoom(userId);
			if(roomId == null){
				console.log(3);
				return;
			}

			//如果游戏未开始，则不可以
			if(socket.gameMgr.hasBegan(roomId) == false){
				console.log(4);
				return;
			}

			var ret = socket.gameMgr.dissolveRequest(roomId,userId);
			if(ret != null){
				var dr = ret.dr!;
				var ramaingTime = (dr.endTime - Date.now()) / 1000;
				var noticeData = {
					time:ramaingTime,
					states:dr.states
				}
				console.log(5);
				userMgr.broacastInRoom('dissolve_notice_push',noticeData,userId,true);
			}
			console.log(6);
		});

		socket.on('dissolve_agree',function(data){
			var userId = socket.userId;

			if(userId == null){
				return;
			}

			var roomId = roomMgr.getUserRoom(userId);
			if(roomId == null){
				return;
			}

			var ret = socket.gameMgr.dissolveAgree(roomId,userId,true);
			if(ret != null){
				var dr = ret.dr!;
				var ramaingTime = (dr.endTime - Date.now()) / 1000;
				var noticeData = {
					time:ramaingTime,
					states:dr.states
				}
				userMgr.broacastInRoom('dissolve_notice_push',noticeData,userId,true);

				var doAllAgree = true;
				for(var i = 0; i < dr.states.length; ++i){
					if(dr.states[i] == false){
						doAllAgree = false;
						break;
					}
				}

				if(doAllAgree){
					socket.gameMgr.doDissolve(roomId);
				}
			}
		});

		socket.on('dissolve_reject',function(data){
			var userId = socket.userId;

			if(userId == null){
				return;
			}

			var roomId = roomMgr.getUserRoom(userId);
			if(roomId == null){
				return;
			}

			var ret = socket.gameMgr.dissolveAgree(roomId,userId,false);
			if(ret != null){
				userMgr.broacastInRoom('dissolve_cancel_push',{},userId,true);
			}
		});

		//断开链接
		socket.on('disconnect',function(reason){
			var userId = socket.userId;
			if(!userId){
				return;
			}

			//如果是旧链接断开，则不需要处理。
			if(userMgr.get(userId) != socket){
				return;
			}

			var data = {
				userid:userId,
				online:false
			};

			//通知房间内其它玩家
			userMgr.broacastInRoom('user_state_push',data,userId);

			//清除玩家的在线信息
			userMgr.del(userId);
			socket.userId = null;
		});

		socket.on('game_ping',function(data){
			var userId = socket.userId;
			if(!userId){
				return;
			}
			//console.log('game_ping');
			socket.emit('game_pong');
		});
	});

	// 返回 http.Server，交给 app.js 汇总成启动横幅（见 utils/startup.ts）
	return httpServer;
};
