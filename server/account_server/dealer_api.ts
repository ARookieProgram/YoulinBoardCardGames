import * as crypto from "../utils/crypto";
import express from "express";
import type { Request, Response, NextFunction } from "express";
import type { Server } from "node:http";
import * as db from "../utils/db";
import * as http from "../utils/http";
import type { AccountServerConfig } from "../types/config";
import type { UserBriefRow } from "../types/db_rows";

/**
 * 渠道/代理 API（:12581），与账号服同进程（见 account_server/app.js）。
 *
 * 迁移说明（见 docs/ai-native/typescript-migration.md §4、server/AGENTS.md §7.5）：
 * 本地 `send(res, ret)` 按账号服的历史约定原样保留（本文件的两个接口实际都走 `http.send`）。
 */

var app = express();

// 本地 JSON 出口：账号服的历史约定（不要改成 utils/http.ts 的 send）
function send(res: Response,ret: Record<string, unknown>): void {
	var str = JSON.stringify(ret);
	res.send(str)
}


/**
 * 启动渠道/代理 API 服务。
 *
 * @param config 账号服配置（configs_*.ts 的 account_server()）。
 * @returns http.Server，交给 account_server/app.js 汇总成启动横幅。
 */
export function start(config: AccountServerConfig): Server {
	// 返回 http.Server，交给 app.js 汇总成启动横幅（见 utils/startup.js）
	return app.listen(config.DEALDER_API_PORT,config.DEALDER_API_IP);
};

//设置跨域访问
app.all('*', function(req: Request, res: Response, next: NextFunction) {
    res.header("Access-Control-Allow-Origin", "*");
    res.header("Access-Control-Allow-Headers", "X-Requested-With");
    res.header("Access-Control-Allow-Methods","PUT,POST,GET,DELETE,OPTIONS");
    res.header("X-Powered-By",' 3.2.1')
    res.header("Content-Type", "application/json;charset=utf-8");
    next();
});

// get_user_data_by_userid 的 SELECT 列表里没有 headimg 列（见 utils/db.ts），
// 原实现读到的 data.headimg 恒为 undefined；这里把这个字段按"可能存在的列"用交叉类型放出来，
// 保持返回结构逐字不变（而不是顺手删字段）
type DealerUserRow = UserBriefRow & { headimg?: unknown };

app.get('/get_user_info',function(req: Request,res: Response){
	var userid = http.queryString(req, "userid");
	db.get_user_data_by_userid(userid,function (data: DealerUserRow | null) {
		if(data){
			var ret = {
				userid:userid,
				name:data.name,
				gems:data.gems,
				headimg:data.headimg
			}
			http.send(res,0,"ok",ret);
		}
		else{
			http.send(res,1,"null");
		}
	});
});

app.get('/add_user_gems',function(req: Request,res: Response){
	var userid = http.queryString(req, "userid");
	var gems = http.queryString(req, "gems");
	db.add_user_gems(userid,gems,function(suc: boolean){
		if(suc){
			http.send(res,0,"ok");
		}
		else{
			http.send(res,1,"failed");
		}
	});
});
