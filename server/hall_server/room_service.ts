import express from "express";
import type { Request, Response } from "express";

import * as crypto from "../utils/crypto";
import * as db from "../utils/db";
import * as http from "../utils/http";

import type { HallServerConfig } from "../types/config";

var app = express();

var hallIp: string | null = null;
// `config` 由 `start($config)` 在开始监听前赋值，所有请求处理里必然已经就绪；
// 下面的 `config!` 只是把这一点写出来，不改变任何运行时行为。
var config: HallServerConfig | null = null;
var rooms: Record<string, string> = {};
var serverMap: Record<string, ServerInfoInput> = {};
var roomIdOfUsers: Record<string, string> = {};

/**
 * 游戏服通过 `/register_gs` 上报并在本文件里登记的一份信息（字段拼写与迁移前一致）。
 *
 * `clientip` / `clientport` 是 `/enter_room` 成功后回给客户端的连接地址，登记时必有，
 * 所以标成必填——否则 `enterInfo` 里会出现 `undefined`，而 JSON 序列化会把该字段整个丢掉，
 * 那才是行为改变。`clientport` / `httpPort` / `load` 都直接来自 query string，因此是字符串；
 * `chooseServer` 里的 `load` 比较也照旧按字符串比，不改成数值。
 */
interface ServerInfo {
	ip?: string;
	id?: string;
	clientip: string;
	clientport: string;
	httpPort?: string | number;
	load?: string;
}

/** 新登记一台游戏服、并回应游戏服心跳时用的那份信息（每次都从 query 重建）。 */
type ServerInfoInput = ServerInfo;

/** `createRoom` / `enterRoom` 交给调用方的进房信息：`token` 由游戏服 `/enter_room` 下发。 */
export interface EnterInfo {
	ip?: string;
	port?: string;
	token: string;
}

/** 客户端传来的 userId：`t_users.userid` 是 INT，但老代码一律按字符串拼签名与 query。 */
type UserId = string | number;

/** 大厅服调游戏服那四个内部接口返回体里本文件用到的字段。 */
interface ShardResponse {
	errcode: number;
	errmsg: unknown;
	roomid: string;
	token: string;
	runing: boolean;
	userroominfo: unknown;
}

//设置跨域访问
app.all('*', function(req: Request, res: Response, next) {
	res.header("Access-Control-Allow-Origin", "*");
	res.header("Access-Control-Allow-Headers", "X-Requested-With");
	res.header("Access-Control-Allow-Methods","PUT,POST,GET,DELETE,OPTIONS");
	res.header("X-Powered-By",' 3.2.1');
	res.header("Content-Type", "application/json;charset=utf-8");
	next();
});

app.get('/register_gs',function(req: Request,res: Response){
	
	// @types/express 把 req.ip 标成 string | undefined（trust proxy 的边界情况）；
	// 这里与迁移前一样直接按字符串使用，不加存在性判断，行为逐字不变。
	var ip = req.ip as string;
	var clientip = http.queryString(req,"clientip");
	var clientport = http.queryString(req,"clientport");
	var httpPort = http.queryString(req,"httpPort");
	var load = http.queryString(req,"load");
	var id = clientip + ":" + clientport;

	if(serverMap[id]){
		var info = serverMap[id];
		if(info.clientport != clientport
			|| info.httpPort != httpPort
			|| info.ip != ip
		){
			console.log("duplicate gsid:" + id + ",addr:" + ip + "(" + httpPort + ")");
			http.send(res,1,"duplicate gsid:" + id);
			return;
		}
		info.load = load;
		http.send(res,0,"ok",{ip:ip});
		return;
	}
	var newInfo: ServerInfoInput = {
		ip:ip,
		id:id,
		// 上面的 id 已经用 `clientip + ":" + clientport` 算过；这里显式 String(...)，
		// 与老代码把值直接放进对象的隐式转字符串结果相同（缺参数时一样是 "undefined"）。
		clientip:String(clientip),
		clientport:String(clientport),
		httpPort:httpPort,
		load:load
	};
	serverMap[id] = newInfo;
	http.send(res,0,"ok",{ip:ip});
	console.log("game server registered.\n\tid:" + id + "\n\taddr:" + ip + "\n\thttp port:" + httpPort + "\n\tsocket clientport:" + clientport);

	var reqdata: http.QueryParams = {
		serverid:id,
		sign:crypto.md5(id+config!.ROOM_PRI_KEY)
	};
	//获取服务器信息
	http.get(ip,httpPort as number | undefined,"/get_server_info",reqdata,function(result){
		if(!result.ok){
			// 原来是 `ret && data.errcode == 0` 才做处理；网络失败时 ret 为 false，什么都不做。
			return;
		}
		// 返回体来自游戏服 `http_service.js`，字段是我们的内部约定；断言只是把 JSON 的
		// unknown 收窄回迁移前的读法，不做任何运行时判断（原来也没有）。
		var data = result.data as unknown as ShardResponse;
		if(data.errcode == 0){
			var userroominfo = data.userroominfo as unknown[];
			for(var i = 0; i < userroominfo.length; i += 2){
				var userId = userroominfo[i];
				var roomId = userroominfo[i+1];
			}
		}
		else{
			console.log(data.errmsg);
		}
	});
});

function chooseServer(): ServerInfo | null {
	var serverinfo: ServerInfo | null = null;
	for(var s in serverMap){
		var info = serverMap[s];
		// 两次读同一个字段；取到局部变量是为了让类型检查器知道它们已经存在
		// （取值与比较方式都没变，`load` 仍按字符串比较）。
		var newLoad = info.load;
		if(serverinfo == null){
			serverinfo = info;			
		}
		else{
			var oldLoad = serverinfo.load;
			if(oldLoad != null && newLoad != null && oldLoad > newLoad){
				serverinfo = info;
			}
		}
	}	
	return serverinfo;
}

export function createRoom(account: string | undefined,userId: UserId,roomConf: string | number | boolean | null | undefined,fnCallback: (errcode: number,roomId: string | null) => void){
	const serverinfo = chooseServer();
	if(serverinfo == null){
		fnCallback(101,null);
		return;
	}
	db.get_gems(account,function(data: { gems: number } | null){
		if(data != null){
			//2、请求创建房间
			var reqdata: http.QueryParams = {
				userid:userId,
				gems:data.gems,
				// 客户端传来的建房配置：它本来就是 query 里的一个 JSON 字符串，这里按老代码原样带上。
				conf:roomConf as string
			}
			// 签名拼接顺序与游戏服 http_service.js 完全一致：userId + conf + gems + ROOM_PRI_KEY。
			// 这里显式写成 String(...)，与老代码的隐式转字符串是同一个结果。
			reqdata.sign = crypto.md5(String(userId) + String(roomConf) + String(data.gems) + config!.ROOM_PRI_KEY);
			http.get(serverinfo.ip as string,serverinfo.httpPort as number | undefined,"/create_room",reqdata,function(result){
				//console.log(data);
				if(!result.ok){
					// 原来是 `ret` 为真才走成功分支；网络失败时 ret 为 false，直接回 102。
					fnCallback(102,null);
					return;
				}
				// 返回体来自游戏服 /create_room；断言只是收窄 JSON 的 unknown，行为不变。
				var data = result.data as unknown as ShardResponse;
				if(data.errcode == 0){
					fnCallback(0,data.roomid);
				}
				else{
					fnCallback(data.errcode,null);		
				}
			});	
		}
		else{
			fnCallback(103,null);
		}
	});
}

export function enterRoom(userId: UserId,name: string | null,roomId: string | null | undefined,fnCallback: (errcode: number,enterInfo: EnterInfo | null) => void){
	var reqdata: http.QueryParams = {
		userid:userId,
		name:name,
		roomid:roomId
	}
	// 签名拼接顺序与游戏服 http_service.js 完全一致：userId + name + roomId + ROOM_PRI_KEY。
	// 显式的 String(...) 与老代码的隐式转字符串结果相同（null 一样变成 "null"）。
	reqdata.sign = crypto.md5(String(userId) + String(name) + String(roomId) + config!.ROOM_PRI_KEY);

	var checkRoomIsRuning = function(serverinfo: ServerInfo,roomId: string | null | undefined,callback: (isRuning: boolean) => void){
		// 与游戏服 /is_room_runing 的校验一致：md5(roomId + ROOM_PRI_KEY)。
		var sign = crypto.md5(String(roomId) + config!.ROOM_PRI_KEY);
		http.get(serverinfo.ip as string,serverinfo.httpPort as number | undefined,"/is_room_runing",{roomid:roomId,sign:sign},function(result){
			if(!result.ok){
				// 原来是 `ret` 为假的分支；网络失败等价于"没在跑"。
				callback(false);
				return;
			}
			// 返回体来自游戏服 /is_room_runing；断言只是收窄 JSON 的 unknown，行为不变。
			var data = result.data as unknown as ShardResponse;
			if(data.errcode == 0 && data.runing == true){
				callback(true);
			}
			else{
				callback(false);
			}
		});
	}

	var enterRoomReq = function(serverinfo: ServerInfo){
		http.get(serverinfo.ip as string,serverinfo.httpPort as number | undefined,"/enter_room",reqdata,function(result){
			if(!result.ok){
				// 原来是 `ret` 为假的分支。
				fnCallback(-1,null);
				return;
			}
			// 返回体来自游戏服 /enter_room；断言只是收窄 JSON 的 unknown，行为不变。
			var data = result.data as unknown as ShardResponse;
			console.log(data);
			if(data.errcode == 0){
				db.set_room_id_of_user(userId,roomId,function(ret: boolean){
					fnCallback(0,{
						ip:serverinfo.clientip,
						port:serverinfo.clientport,
						token:data.token
					});
				});
			}
			else{
				console.log(data.errmsg);
				fnCallback(data.errcode,null);
			}
		});
	}

	var chooseServerAndEnter = function(serverinfo: ServerInfo | null){
		serverinfo = chooseServer();
		if(serverinfo != null){
			enterRoomReq(serverinfo);
		}
		else{
			fnCallback(-1,null);					
		}
	}

	db.get_room_addr(roomId,function(ret: boolean,ip: string | null,port: number | null){
		if(ret){
			var id = ip + ":" + port;
			var serverinfo = serverMap[id];
			if(serverinfo != null){
				checkRoomIsRuning(serverinfo,roomId,function(isRuning: boolean){
					if(isRuning){
						enterRoomReq(serverinfo);
					}
					else{
						chooseServerAndEnter(serverinfo);
					}
				});
			}
			else{
				chooseServerAndEnter(serverinfo);
			}
		}
		else{
			fnCallback(-2,null);
		}
	});
}

export function start($config: HallServerConfig){
	config = $config;
	// 返回 http.Server，交给 app.js 汇总成启动横幅（见 utils/startup.js）
	return app.listen(config.ROOM_PORT,config.FOR_ROOM_IP);
}
