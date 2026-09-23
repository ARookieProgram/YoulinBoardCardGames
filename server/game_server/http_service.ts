import * as nodeHttp from "node:http";

import express from "express";

import * as crypto from "../utils/crypto";
import * as db from "../utils/db";
import * as http from "../utils/http";
import * as roomMgr from "./roommgr";
import * as tokenMgr from "./tokenmgr";
import * as userMgr from "./usermgr";

import type { Request, Response, NextFunction } from "express";
import type { GameServerConfig } from "../types/config";
import type { RoomCreateConf } from "../types/domain";

/**
 * 游戏服给大厅服调用的内部 HTTP 接口。
 *
 * 四个接口（`/get_server_info`、`/create_room`、`/enter_room`、`/is_room_runing`）**都校验 `sign`**，
 * `/get_server_info` 用的是 `md5(serverid + ROOM_PRI_KEY)`，其余三个与登录链路同源
 * （拼接顺序见各处理器，任何改动都会导致大厅服调不通）。
 */

var app = express();
var config: GameServerConfig | null = null;

var serverIp = "";

//测试
app.all('*', function(req: Request, res: Response, next: NextFunction) {
	res.header("Access-Control-Allow-Origin", "*");
	res.header("Access-Control-Allow-Headers", "X-Requested-With");
	res.header("Access-Control-Allow-Methods","PUT,POST,GET,DELETE,OPTIONS");
	res.header("X-Powered-By",' 3.2.1');
	res.header("Content-Type", "application/json;charset=utf-8");
	next();
});

app.get('/get_server_info',function(req,res){
	var serverId = http.queryString(req,"serverid");
	var sign = http.queryString(req,"sign");
	console.log(serverId);
	console.log(sign);
	if(serverId  != config!.SERVER_ID || sign == null){
		http.send(res,1,"invalid parameters");
		return;
	}

	var md5 = crypto.md5(serverId + config!.ROOM_PRI_KEY);
	if(md5 != sign){
		http.send(res,1,"sign check failed.");
		return;
	}

	var locations = roomMgr.getUserLocations();
	var arr: string[] = [];
	for(var userId in locations){
		var location = locations[userId];
		// for...in 只会枚举真实存在的键，这里的判空不会触发；写上它只是为了满足类型收窄。
		if(location == null){
			continue;
		}
		var roomId = location.roomId;
		arr.push(userId);
		arr.push(roomId);
	}
	http.send(res,0,"ok",{userroominfo:arr});
});

app.get('/create_room',function(req,res){
	var userId = http.queryInt(req,"userid");
	var sign = http.queryString(req,"sign");
	var gems = http.queryString(req,"gems");
	var conf = http.queryString(req,"conf")
	if(userId == null || sign == null || conf == null){
		http.send(res,1,"invalid parameters");
		return;
	}

	var md5 = crypto.md5(userId + conf + gems + config!.ROOM_PRI_KEY);
	if(md5 != sign){
		console.log("invalid reuqest.");
		http.send(res,1,"sign check failed.");
		return;
	}

	var roomConf: RoomCreateConf = JSON.parse(conf);
	// 原实现把 query 里的字符串直接当 gems 用（`cost > gems` 靠 JS 隐式转数字）。
	// Number() 正是 `>` 的 ToNumber 语义，因此这里数值比较的结果与原来完全一致，
	// 而 md5 仍然用原始字符串。
	roomMgr.createRoom(userId,roomConf,Number(gems),serverIp,config!.CLIENT_PORT,function(errcode,roomId){
		if(errcode != 0 || roomId == null){
			http.send(res,errcode,"create failed.");
			return;
		}
		else{
			http.send(res,0,"ok",{roomid:roomId});
		}
	});
});

app.get('/enter_room',function(req,res){
	var userId = http.queryInt(req,"userid");
	var name = http.queryString(req,"name");
	var roomId = http.queryString(req,"roomid");
	var sign = http.queryString(req,"sign");
	if(userId == null || roomId == null || sign == null){
		http.send(res,1,"invalid parameters");
		return;
	}

	var md5 = crypto.md5(userId + name! + roomId + config!.ROOM_PRI_KEY);
	console.log(req.query);
	console.log(md5);
	if(md5 != sign){
		http.send(res,2,"sign check failed.");
		return;
	}

	//安排玩家坐下
	// name 同上：只有签名对得上才会走到这里，此时它必然是字符串（缺失时 md5 不可能匹配）。
	roomMgr.enterRoom(roomId,userId,name!,function(ret){
		if(ret != 0){
			if(ret == 1){
				http.send(res,4,"room is full.");
			}
			else if(ret == 2){
				http.send(res,3,"can't find room.");
			}
			return;
		}

		var token = tokenMgr.createToken(userId,5000);
		http.send(res,0,"ok",{token:token});
	});
});

app.get('/is_room_runing',function(req,res){
	var roomId = http.queryString(req,"roomid");
	var sign = http.queryString(req,"sign");
	if(roomId == null || sign == null){
		http.send(res,1,"invalid parameters");
		return;
	}

	var md5 = crypto.md5(roomId + config!.ROOM_PRI_KEY);
	if(md5 != sign){
		http.send(res,2,"sign check failed.");
		return;
	}

	//var roomInfo = roomMgr.getRoom(roomId);
	http.send(res,0,"ok",{runing:true});
});

/**
 * 心跳上报给大厅服的载荷。
 *
 * 用 `http.QueryParams` 描述：它最终就是被 `querystring.stringify` 拼进 URL 的一组键值，
 * 与原实现里那个动态对象一一对应。
 */
var gameServerInfo: http.QueryParams = {};
var lastTickTime = 0;

//向大厅服定时心跳
function update(): void {
	// config 由 start() 赋值，而这个定时器也是 start() 里注册的；开头的非空断言只为对齐类型
	// （启动后 config 不再变化，取一次局部量与原实现每次读模块变量等价）。
	var cfg = config!;
	if(lastTickTime + cfg.HTTP_TICK_TIME < Date.now()){
		lastTickTime = Date.now();
		gameServerInfo.load = roomMgr.getTotalRooms();
		http.get(cfg.HALL_IP,cfg.HALL_PORT,"/register_gs",gameServerInfo,function(result){
			if(result.ok){
				var data = result.data;
				if(data.errcode != 0){
					console.log(data.errmsg);
				}

				if(data.ip != null){
					// 原来是把响应当中的 ip 原样赋给 serverIp；JSON 里它就是字符串，
					// 这里用 String() 收窄，非字符串的畸形响应也仍然是"有值就用"。
					serverIp = String(data.ip);
				}
			}
			else{
				//
				lastTickTime = 0;
			}
		});

		var mem = process.memoryUsage();
		var format = function(bytes: number): string {
              return (bytes/1024/1024).toFixed(2)+'MB';
        };
		//console.log('Process: heapTotal '+format(mem.heapTotal) + ' heapUsed ' + format(mem.heapUsed) + ' rss ' + format(mem.rss));
	}
}

/**
 * 启动内部 HTTP 服务。
 *
 * @param $config 游戏服配置。
 * @returns 该进程的 http.Server（交给 app.ts 汇总成启动横幅）。
 */
export function start($config: GameServerConfig): nodeHttp.Server {
	config = $config;

	//
	gameServerInfo = {
		id:$config.SERVER_ID,
		clientip:$config.CLIENT_IP,
		clientport:$config.CLIENT_PORT,
		httpPort:$config.HTTP_PORT,
		load:roomMgr.getTotalRooms(),
	};

	setInterval(update,1000);
	// 返回 http.Server，交给 app.js 汇总成启动横幅（见 utils/startup.ts）
	return app.listen($config.HTTP_PORT,$config.FOR_HALL_IP);
};
