import type { Server } from 'node:http';

import * as startup from '../utils/startup';
import * as db from '../utils/db';
import { loadConfigs } from '../utils/config';
import * as bancheck from '../utils/bancheck';

// client_service / room_service 仍然用 require 而不是 import：import 会被编译器提到文件顶部，
// 改变原实现的模块求值顺序（先加载这两个 service，再加载 startup / db）。
// 右侧写成 `typeof import(...)`，拿到的是它们真实的导出类型，不需要额外的接口声明。
var client_service: typeof import('./client_service') = require('./client_service');
var room_service: typeof import('./room_service') = require('./room_service');

var configs = loadConfigs(process.argv[2], __dirname);
var config = configs.hall_server();

//封禁校验（登录 / 建房 / 进房前问管理平台）。配置见 configs_*.ts 的 ban_check()。
bancheck.init(configs.ban_check());

var mysqlConf = configs.mysql();

db.init(mysqlConf);

var clientServer = client_service.start(config);
var roomServer = room_service.start(config);

//大厅服 = 9001 给客户端、9002 接收游戏服上报与注册
startup.report({
	title:'大厅服 (hall_server)',
	configFile:process.argv[2],
	note:'大厅服已就绪，按 Ctrl+C 停止服务。',
	db:db,
	dbLabel:mysqlConf.DB + '@' + mysqlConf.HOST + ':' + mysqlConf.PORT,
	endpoints:[
		{server:clientServer,label:'客户端 HTTP',scheme:'http',host:config.HALL_IP,port:config.CLEINT_PORT,note:'/login /enter_private_room'},
		{server:roomServer,label:'游戏服上报 HTTP',scheme:'http',host:config.FOR_ROOM_IP,port:config.ROOM_PORT,note:'/register_gs'}
	]
});
