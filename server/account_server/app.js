var db = require('../utils/db');
var startup = require('../utils/startup');
var configs = require(process.argv[2]);

var mysqlConf = configs.mysql();

//init db pool.
db.init(mysqlConf);

var config = configs.account_server();

var as = require('./account_server');
var accountServer = as.start(config);

var dapi = require('./dealer_api');
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
