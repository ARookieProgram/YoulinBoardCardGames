import type { Server } from 'node:http';

import * as startup from '../utils/startup';
import * as db from '../utils/db';
import { loadConfigs } from '../utils/config';
import * as bancheck from '../utils/bancheck';

// http_service / socket_service 仍然用 require 而不是 import：import 会被编译器提到文件顶部，
// 改变原实现的模块求值顺序（先加载这两个 service，再加载 startup / db）。
// 右侧写成 `typeof import(...)`，拿到的是它们真实的导出类型，不需要额外的接口声明。
var http_service: typeof import('./http_service') = require('./http_service');
var socket_service: typeof import('./socket_service') = require('./socket_service');

//从配置文件获取服务器信息
var configs = loadConfigs(process.argv[2], __dirname);
var config = configs.game_server();

//封禁校验（socket 登录 / 进房前问管理平台）。配置见 configs_*.ts 的 ban_check()。
bancheck.init(configs.ban_check());

var mysqlConf = configs.mysql();

db.init(mysqlConf);

//开启HTTP服务（供大厅服调用）
var httpServer = http_service.start(config);

//开启外网SOCKET服务（客户端对局协议）
var socketServer = socket_service.start(config);

startup.report({
	title:'游戏服 (game_server)',
	configFile:process.argv[2],
	note:'游戏服已就绪，按 Ctrl+C 停止服务。',
	db:db,
	dbLabel:mysqlConf.DB + '@' + mysqlConf.HOST + ':' + mysqlConf.PORT,
	endpoints:[
		{server:socketServer,label:'客户端 Socket.IO',scheme:'http',host:config.CLIENT_IP,port:config.CLIENT_PORT,note:'对局协议'},
		{server:httpServer,label:'内部 HTTP',scheme:'http',host:config.FOR_HALL_IP,port:config.HTTP_PORT,note:'供大厅服调用，需签名'}
	]
});

//require('./gamemgr');
