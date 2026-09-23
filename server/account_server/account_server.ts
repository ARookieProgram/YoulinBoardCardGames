import * as crypto from "../utils/crypto";
import express from "express";
import type { Request, Response, NextFunction } from "express";
import type { Server } from "node:http";
import * as db from "../utils/db";
import * as http from "../utils/http";
import type { AccountServerConfig } from "../types/config";
import type { AccountRow, UserBaseInfoRow } from "../types/db_rows";

/**
 * 账号服 HTTP 服务（:9000）：注册 / 登录 / 游客 / 微信登录 / 头像代理。
 *
 * 迁移说明（见 docs/ai-native/typescript-migration.md §4、server/AGENTS.md §7.5）：
 * 账号服历史上没有跟进 `utils/http.ts` 的统一出口，本文件保留自己的本地 `send(res, ret)`，
 * 返回结构也比大厅服/游戏服随意；这里只补类型，不改返回结构。
 */

var app = express();
var hallAddr = "";

// 本地 JSON 出口：账号服的历史约定（不要改成 utils/http.ts 的 send）
function send(res: Response,ret: Record<string, unknown>): void {
	var str = JSON.stringify(ret);
	res.send(str)
}

/**
 * 历史 bug 的忠实保留（见 `/auth` 处理器的说明）。
 *
 * 原 `account_server.js` 的 `/auth` 分支调用了一个**本文件从未定义**的 `get_md5`，
 * 因此那一分支必然抛 ReferenceError。迁移的目标是行为不变，所以这里不是"补上实现"，
 * 而是把这个必然抛错的事实写成一个能通过编译的桩：调用点、抛错类型与原实现一致。
 *
 * @param content 原实现想签名的内容（本桩不使用）。
 * @returns 永不返回。
 */
function get_md5(content: string): string {
	throw new ReferenceError("get_md5 is not defined");
}

// 由 start() 在 listen 之前赋值；原实现写作 var config = null
var config: AccountServerConfig;

/**
 * 启动账号服 HTTP 服务。
 *
 * @param cfg 账号服配置（configs_*.ts 的 account_server()）。
 * @returns http.Server，交给 account_server/app.js 汇总成启动横幅。
 */
export function start(cfg: AccountServerConfig): Server {
	config = cfg;
	hallAddr = config.HALL_IP  + ":" + config.HALL_CLIENT_PORT;
	// 返回 http.Server，交给 app.js 汇总成启动横幅（见 utils/startup.js）
	return app.listen(config.CLIENT_PORT);
}




//设置跨域访问
app.all('*', function(req: Request, res: Response, next: NextFunction) {
    res.header("Access-Control-Allow-Origin", "*");
    res.header("Access-Control-Allow-Headers", "X-Requested-With");
    res.header("Access-Control-Allow-Methods","PUT,POST,GET,DELETE,OPTIONS");
    res.header("X-Powered-By",' 3.2.1')
	res.header("Content-Type", "application/json;charset=utf-8");
	next();
});

app.get('/register',function(req: Request,res: Response){
	var account = http.queryString(req, "account");
	var password = http.queryString(req, "password");

	var fnFailed = function(): void {
		send(res,{errcode:1,errmsg:"account has been used."});
	};

	var fnSucceed = function(): void {
		send(res,{errcode:0,errmsg:"ok"});	
	};

	db.is_user_exist(account,function(exist: boolean){
		if(exist){
			db.create_account(account,password,function(ret: boolean){
				if (ret) {
					fnSucceed();
				}
				else{
					fnFailed();
				}
			});
		}
		else{
			fnFailed();
			console.log("account has been used.");			
		}
	});
});

app.get('/get_version',function(req: Request,res: Response){
	var ret = {
		version:config.VERSION,
	}
	send(res,ret);
});

app.get('/get_serverinfo',function(req: Request,res: Response){
	var ret = {
		version:config.VERSION,
		hall:hallAddr,
		appweb:config.APP_WEB,
	}
	send(res,ret);
});

app.get('/guest',function(req: Request,res: Response){
	var account = "guest_" + http.queryString(req, "account");
	// 原实现直接拼 req.ip：express 的类型把它标成 string | undefined，
	// 这里与迁移前一样按字符串用（断言不产生任何运行时代码），不加存在性判断，行为逐字不变
	var sign = crypto.md5(account + (req.ip as string) + config.ACCOUNT_PRI_KEY);
	var ret = {
		errcode:0,
		errmsg:"ok",
		account:account,
		halladdr:hallAddr,
		sign:sign
	}
	send(res,ret);
});

app.get('/auth',function(req: Request,res: Response){
	var account = http.queryString(req, "account");
	var password = http.queryString(req, "password");

	db.get_account_info(account,password,function(info: AccountRow | null){
		if(info == null){
			send(res,{errcode:1,errmsg:"invalid account"});
			return;
		}

        var account = "vivi_" + http.queryString(req, "account");
        // 历史 bug（迁移不修）：原实现调用的是本文件从未定义的 get_md5()。
        // 这行位于 db 的异步回调里，抛出的 ReferenceError 不会被 express 捕获，账号服进程会直接退出。
        // 迁移只把"必然抛错"这个事实写成可读的桩函数，不改行为；要修请单独开一次改动（改用 crypto.md5）。
        var sign = get_md5(account + (req.ip as string) + config.ACCOUNT_PRI_KEY);
        var ret = {
            errcode:0,
            errmsg:"ok",
            account:account,
            sign:sign
        }
        send(res,ret);
	});
});

/** 微信开放平台的应用信息：键是 /wechat_auth 的 os 参数（Android / iOS）。 */
interface WechatApp {
	appid: string;
	secret: string;
}

var appInfo: Record<string, WechatApp | undefined> = {
	Android:{
		appid:"wxe39f08522d35c80c",
		secret:"fa88e3a3ca5a11b06499902cea4b9c01",
	},
	iOS:{
		appid:"wxcb508816c5c4e2a4",
		secret:"7de38489ede63089269e3410d5905038",		
	}
};

function get_access_token(code: string,os: string,callback: http.HttpCallback): void {
	var info = appInfo[os];
	if(info == null){
		// 原实现这里没有 return，回调之后还会继续往下走并在 info.appid 处抛异常；
		// info! 保留同样的取值路径（未知 os 时同样抛 TypeError），只用于通过类型检查
		callback({ ok: false, error: new Error("unknown os: " + os) });
	}
	var data: http.QueryParams = {
		appid:info!.appid,
		secret:info!.secret,
		code:code,
		grant_type:"authorization_code"
	};

	http.get2("https://api.weixin.qq.com/sns/oauth2/access_token",data,callback,true);
}

function get_state_info(access_token: string,openid: string,callback: http.HttpCallback): void {
	var data: http.QueryParams = {
		access_token:access_token,
		openid:openid
	};

	http.get2("https://api.weixin.qq.com/sns/userinfo",data,callback,true);
}

function create_user(account: string,name: string,sex: number,headimgurl: string,callback: () => void): void {
	var coins = 1000;
	var gems = 21;
	db.is_user_exist(account,function(ret: boolean){
		if(!ret){
			db.create_user(account,name,coins,gems,sex,headimgurl,function(ret: unknown){
				callback();
			});
		}
		else{
			db.update_user_info(account,name,headimgurl,sex,function(ret: unknown){
				callback();
			});
		}
	});
};
app.get('/wechat_auth',function(req: Request,res: Response){
	var code = http.queryString(req, "code");
	var os = http.queryString(req, "os");
	if(code == null || code == "" || os == null || os == ""){
		return;
	}
	console.log(os);
	get_access_token(code,os,function(result: http.HttpResult){
		if(result.ok){
			// 微信接口的字段在 JsonObject 里是 unknown，按接口契约在边界处收窄
			var access_token = result.data.access_token as string;
			var openid = result.data.openid as string;
			get_state_info(access_token,openid,function(result2: http.HttpResult){
				if(result2.ok){
					var openid = result2.data.openid as string;
					var nickname = result2.data.nickname as string;
					var sex = result2.data.sex as number;
					var headimgurl = result2.data.headimgurl as string;
					var account = "wx_" + openid;
					create_user(account,nickname,sex,headimgurl,function(){
						var sign = crypto.md5(account + (req.ip as string) + config.ACCOUNT_PRI_KEY);
					    var ret = {
					        errcode:0,
					        errmsg:"ok",
					        account:account,
					        halladdr:hallAddr,
					        sign:sign
					    };
					    send(res,ret);
					});						
				}
			});
		}
		else{
			send(res,{errcode:-1,errmsg:"unkown err."});
		}
	});
});

app.get('/base_info',function(req: Request,res: Response){
	var userid = http.queryString(req, "userid");
	db.get_user_base_info(userid,function(data: UserBaseInfoRow | null){
		// 原实现不做空判断：userid 缺失时 db 会回调 null，这里同样在取字段时抛 TypeError（行为不变），
		// data! 只用于通过类型检查
		var ret = {
	        errcode:0,
	        errmsg:"ok",
			name:data!.name,
			sex:data!.sex,
	        headimgurl:data!.headimg
	    };
	    send(res,ret);
	});
});

app.get('/image', function (req: Request, res: Response) {
	var url = http.queryString(req, "url");
	if (!url) {
	  http.send(res, 1, 'invalid url', {});
	  return;
	}
	if(url.search('http://') != 0 && url.search('https://') != 0){
		http.send(res, 1, 'invalid url', {});
		return;
	}

	url = url.split('.jpg')[0];
	

	var safe = url.search('https://') == 0;
	console.log(url);
	// 代理拉取远程图片：异步回调写法，拿到原始字节后再回写响应。
	// 原实现给 data 传 null：getRaw 的形参类型是 QueryParams，而 querystring.stringify(null)
	// 与 querystring.stringify({}) 都是空串，请求 URL 完全一致。
	http.getRaw(url, {}, safe, 'binary', function (type: string | undefined | null, data: http.JsonObject | string | null) {
		if (!type || !data) {
			// 原实现传的是 `true`：迁移前的 http.js 是非严格模式，给 boolean 挂 errcode/errmsg 只是静默失效，
			// 响应体因此是 JSON.stringify(true) == "true"。迁移后的 http.ts 带 "use strict"，
			// 再走 http.send(res, 1, 'invalid url', true) 会在 getRaw 的异步回调里抛 TypeError
			// （express 捕获不到，会让账号服进程退出）。这里直接写出原来的响应体：
			// 对外行为逐字不变，又不依赖 sloppy mode。
			res.send(JSON.stringify(true));
			return;
		}
		res.writeHead(200, { "Content-Type": type });
		// encoding 是 'binary'，getRaw 在这个分支只会回传字符串；断言只用于收窄 JsonObject | string
		res.write(data as string, 'binary');
		res.end();
	});
});
