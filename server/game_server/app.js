var http_service = require("./http_service");
var socket_service = require("./socket_service");
var startup = require('../utils/startup');

//从配置文件获取服务器信息
var configs = require(process.argv[2]);
var config = configs.game_server();

var mysqlConf = configs.mysql();

var db = require('../utils/db');
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
