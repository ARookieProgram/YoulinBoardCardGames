import type { Server } from 'node:http';

import * as db from '../utils/db';
import * as startup from '../utils/startup';
import { loadConfigs } from '../utils/config';

// account_server / dealer_api 仍然用 require 而不是 import：import 会被编译器提到文件顶部，
// 改变原实现的模块求值顺序（原实现是 init 完数据库再加载这两个 service）。
// 右侧写成 `typeof import(...)`，拿到的是它们真实的导出类型，不需要额外的接口声明。
var as: typeof import('./account_server') = require('./account_server');
var dapi: typeof import('./dealer_api') = require('./dealer_api');

var configs = loadConfigs(process.argv[2], __dirname);

var mysqlConf = configs.mysql();

//init db pool.
db.init(mysqlConf);

var config = configs.account_server();

var accountServer = as.start(config);

var dealerApi = dapi.start(config);

//账号服 = 同一个进程里的两个 HTTP 服务：9000 给客户端、12581 给渠道/代理
startup.report({
	title:'账号服 (account_server)',
	configFile:process.argv[2],
	note:'账号服已就绪，按 Ctrl+C 停止服务。',
	db:db,
	dbLabel:mysqlConf.DB + '@' + mysqlConf.HOST + ':' + mysqlConf.PORT,
	endpoints:[
		{server:accountServer,label:'客户端 HTTP',scheme:'http',host:config.HALL_IP,port:config.CLIENT_PORT,note:'/guest /register /auth'},
		{server:dealerApi,label:'渠道/代理 API',scheme:'http',host:config.DEALDER_API_IP,port:config.DEALDER_API_PORT}
	]
});
