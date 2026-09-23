import express from "express";
import type { Request, Response } from "express";

import * as crypto from "../utils/crypto";
import * as db from "../utils/db";
import * as http from "../utils/http";
import * as room_service from "./room_service";

import type { HallServerConfig } from "../types/config";
import type { MessageRow, UserBriefRow } from "../types/db_rows";

var app = express();
// `config` 由 `start($config)` 在开始监听前赋值，所有请求处理里必然已经就绪；
// 下面的 `config!` 只是把这一点写出来，不改变任何运行时行为。
var config: HallServerConfig | null = null;

/** `req.query` 在本仓库里的真实形态：express 的类型放宽成了联合类型，这里在边界处收敛为字符串表。 */
type ClientQuery = http.QueryParams;

/** 调用方的 `req`，query 已按本仓库的约定收敛；`check_account` 收这个形状。 */
type ClientRequest = Request & { query: ClientQuery };

/** 客户端传来的 userId：`t_users.userid` 是 INT，但老代码一律按字符串拼签名与 query。 */
type UserId = string | number;

/**
 * `/login` 的返回体：先建对象、命中房间时再补 `roomid`（与迁移前逐字相同）。
 *
 * `sex` 是历史遗留：老代码读的是 `data.sex`，而 `get_user_data` 的 SELECT
 * （`SELECT userid,account,name,lv,exp,coins,gems,roomid`）里**没有 sex 列**，
 * 因此这个字段在运行时恒为 undefined，`JSON.stringify` 会直接把它丢掉。
 * 迁移保持原行为，所以这里声明成可选并如实标注。
 */
interface LoginEntry {
	roomid?: string;
	/** 客户端 IP（已剥掉 `::ffff:` 前缀）。 */
	ip: string;
	account: string;
	userid: number;
	name: string | null;
	lv: number;
	exp: number;
	coins: number;
	gems: number;
	sex?: number | null;
	[key: string]: unknown;
}

/** `/create_private_room`、`/enter_private_room` 的返回体；`sign` 是最后挂上去的进房签名。 */
interface RoomEntry {
	/** `/enter_private_room` 的 roomid 直接取自 query（`queryString` 可能给出 undefined）。 */
	roomid?: string;
	/** 与 room_service 的 `EnterInfo` 一致：这两项就是登记时的 query 字符串。 */
	ip?: string;
	port?: string;
	token: string;
	time: number;
	sign?: string;
	[key: string]: unknown;
}

/**
 * 校验 `account` / `sign` 两个 query 参数是否存在（签名校验本体历史上已被注释掉，保持原样）。
 *
 * @param req express 请求（query 已收敛为字符串表）。
 * @param res express 响应。
 * @returns 参数齐全时 true；否则已经回过错误响应并返回 false。
 */
function check_account(req: ClientRequest, res: Response): boolean {
	var account = req.query.account;
	var sign = req.query.sign;
	if(account == null || sign == null){
		http.send(res,1,"unknown error");
		return false;
	}
	/*
	var serverSign = crypto.md5(account + req.ip + config.ACCOUNT_PRI_KEY);
	if(serverSign != sign){
		http.send(res,2,"login failed.");
		return false;
	}
	*/
	return true;
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

app.get('/login',function(req: Request,res: Response){
	if(!check_account(req as ClientRequest,res)){
		return;
	}
	
	// @types/express 把 req.ip 标成 string | undefined（trust proxy 的边界情况）；
	// 这里与迁移前一样直接按字符串使用，不加存在性判断，行为逐字不变。
	var ip = req.ip as string;
	if(ip.indexOf("::ffff:") != -1){
		ip = ip.substr(7);
	}
	
	var account = http.queryString(req,"account");
	db.get_user_data(account,function(data: UserBriefRow | null){
		if(data == null){
			http.send(res,0,"ok");
			return;
		}

		var ret: LoginEntry = {
			account:data.account,
			userid:data.userid,
			name:data.name,
			lv:data.lv,
			exp:data.exp,
			coins:data.coins,
			gems:data.gems,
			ip:ip,
			// 历史行为：`sex` 不在 get_user_data 的 SELECT 里（见 LoginEntry 的说明），
			// 老代码直接读 `data.sex`，拿到的是 undefined。这里的断言只是让类型说得通，
			// 不做任何运行时判断或补默认值。
			sex:(data as { sex?: number | null }).sex,
		};

		db.get_room_id_of_user(data.userid,function(roomId: string | null){
			//如果用户处于房间中，则需要对其房间进行检查。 如果房间还在，则通知用户进入
			if(roomId != null){
				//检查房间是否存在于数据库中
				db.is_room_exist(roomId,function (retval: boolean){
					if(retval){
						ret.roomid = roomId;
					}
					else{
						//如果房间不在了，表示信息不同步，清除掉用户记录
						db.set_room_id_of_user(data.userid,null);
					}
					http.send(res,0,"ok",ret);
				});
			}
			else {
				http.send(res,0,"ok",ret);
			}
		});
	});
});

app.get('/create_user',function(req: Request,res: Response){
	if(!check_account(req as ClientRequest,res)){
		return;
	}
	var account = http.queryString(req,"account");
	var name = http.queryString(req,"name");
	var coins = 1000;
	var gems = 21;
	console.log(name);

	db.is_user_exist(account,function(ret: boolean){
		if(!ret){
			db.create_user(account,name,coins,gems,0,null,function(ret: boolean){
				if (ret == null) {
					http.send(res,2,"system error.");
				}
				else{
					http.send(res,0,"ok");					
				}
			});
		}
		else{
			http.send(res,1,"account have already exist.");
		}
	});
});

app.get('/create_private_room',function(req: Request,res: Response){
	//验证参数合法性
	var data = req.query as ClientQuery;
	//验证玩家身份
	if(!check_account(req as ClientRequest,res)){
		return;
	}

	var account = http.queryString(req,"account");

	// 保持迁移前的原样：这两个字段会被就地清掉（http.send 之后不回读它们）
	data.account = null;
	data.sign = null;
	var conf = data.conf;
	db.get_user_data(account,function(data: UserBriefRow | null){
		if(data == null){
			http.send(res,1,"system error");
			return;
		}
		var userId = data.userid;
		var name = data.name;
		//验证玩家状态
		db.get_room_id_of_user(userId,function(roomId: string | null){
			if(roomId != null){
				http.send(res,-1,"user is playing in room now.");
				return;
			}
			//创建房间
			room_service.createRoom(account,userId,conf,function(err: number,roomId: string | null){
				if(err == 0 && roomId != null){
					room_service.enterRoom(userId,name,roomId,function(errcode: number,enterInfo: room_service.EnterInfo | null){
						if(enterInfo){
							var ret: RoomEntry = {
								roomid:roomId,
								ip:enterInfo.ip,
								port:enterInfo.port,
								token:enterInfo.token,
								time:Date.now()
							};
							ret.sign = crypto.md5(ret.roomid + ret.token + ret.time + config!.ROOM_PRI_KEY);
							http.send(res,0,"ok",ret);
						}
						else{
							http.send(res,errcode,"room doesn't exist.");
						}
					});
				}
				else{
					http.send(res,err,"create failed.");					
				}
			});
		});
	});
});

app.get('/enter_private_room',function(req: Request,res: Response){
	var data = req.query as ClientQuery;
	var roomId = http.queryString(req,"roomid");
	if(roomId == null){
		http.send(res,-1,"parameters don't match api requirements.");
		return;
	}
	if(!check_account(req as ClientRequest,res)){
		return;
	}

	var account = data.account;

	db.get_user_data(account,function(data: UserBriefRow | null){
		if(data == null){
			http.send(res,-1,"system error");
			return;
		}
		var userId = data.userid;
		var name = data.name;

		//验证玩家状态
		//todo
		//进入房间
		room_service.enterRoom(userId,name,roomId,function(errcode: number,enterInfo: room_service.EnterInfo | null){
			if(enterInfo){
				var ret: RoomEntry = {
					roomid:roomId,
					ip:enterInfo.ip,
					port:enterInfo.port,
					token:enterInfo.token,
					time:Date.now()
				};
				ret.sign = crypto.md5(roomId + ret.token + ret.time + config!.ROOM_PRI_KEY);
				http.send(res,0,"ok",ret);
			}
			else{
				http.send(res,errcode,"enter room failed.");
			}
		});
	});
});

app.get('/get_history_list',function(req: Request,res: Response){
	var data = req.query as ClientQuery;
	if(!check_account(req as ClientRequest,res)){
		return;
	}
	var account = data.account;
	db.get_user_data(account,function(data: UserBriefRow | null){
		if(data == null){
			http.send(res,-1,"system error");
			return;
		}
		var userId = data.userid;
		db.get_user_history(userId,function(history: unknown[] | null){
			http.send(res,0,"ok",{history:history});
		});
	});
});

app.get('/get_games_of_room',function(req: Request,res: Response){
	var data = req.query as ClientQuery;
	var uuid = data.uuid;
	if(uuid == null){
		http.send(res,-1,"parameters don't match api requirements.");
		return;
	}
	if(!check_account(req as ClientRequest,res)){
		return;
	}
	db.get_games_of_room(uuid,function(data: unknown){
		console.log(data);
		http.send(res,0,"ok",{data:data});
	});
});

app.get('/get_detail_of_game',function(req: Request,res: Response){
	var data = req.query as ClientQuery;
	var uuid = data.uuid;
	var index = data.index;
	if(uuid == null || index == null){
		http.send(res,-1,"parameters don't match api requirements.");
		return;
	}
	if(!check_account(req as ClientRequest,res)){
		return;
	}
	db.get_detail_of_game(uuid,index,function(data: unknown){
		http.send(res,0,"ok",{data:data});
	});
});

app.get('/get_user_status',function(req: Request,res: Response){
	if(!check_account(req as ClientRequest,res)){
		return;
	}
	var account = http.queryString(req,"account");
	db.get_gems(account,function(data: { gems: number } | null){
		if(data != null){
			http.send(res,0,"ok",{gems:data.gems});	
		}
		else{
			http.send(res,1,"get gems failed.");
		}
	});
});

app.get('/get_message',function(req: Request,res: Response){
	if(!check_account(req as ClientRequest,res)){
		return;
	}
	var type = http.queryString(req,"type");
	
	if(type == null){
		http.send(res,-1,"parameters don't match api requirements.");
		return;
	}
	
	var version = http.queryString(req,"version");
	db.get_message(type,version,function(data: MessageRow | null){
		if(data != null){
			http.send(res,0,"ok",{msg:data.msg,version:data.version});	
		}
		else{
			http.send(res,1,"get message failed.");
		}
	});
});

export function start($config: HallServerConfig){
	config = $config;
	// 返回 http.Server，交给 app.js 汇总成启动横幅（见 utils/startup.js）
	return app.listen(config.CLEINT_PORT);
}
