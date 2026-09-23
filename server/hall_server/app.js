var client_service = require("./client_service");
var room_service = require("./room_service");
var startup = require('../utils/startup');

var configs = require(process.argv[2]);
var config = configs.hall_server();

var mysqlConf = configs.mysql();

var db = require('../utils/db');
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
