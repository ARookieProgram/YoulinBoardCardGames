import type {
	AccountServerConfig,
	GameServerConfig,
	HallServerConfig,
	MysqlConfig,
	ServerConfigs,
} from "./types/config";

var HALL_IP = "127.0.0.1";//如果非本机访问，这里要变
var HALL_CLIENT_PORT = 9001;
var HALL_ROOM_PORT = 9002;

var ACCOUNT_PRI_KEY = "^&*#$%()@";
var ROOM_PRI_KEY = "~!@#$(*&^%$&";

var LOCAL_IP = 'localhost';

export function mysql():MysqlConfig{
	return {
		HOST:'127.0.0.1',
		USER:'root',
		PSWD:'li663399',//如果连接失败，请检查这里
		DB:'db_scmj',//如果连接失败，请检查这里
		PORT:3306,
	}
}

//账号服配置
export function account_server():AccountServerConfig{
	return {
		CLIENT_PORT:9000,
		HALL_IP:HALL_IP,
		HALL_CLIENT_PORT:HALL_CLIENT_PORT,
		ACCOUNT_PRI_KEY:ACCOUNT_PRI_KEY,
		
		//
		DEALDER_API_IP:LOCAL_IP,
		DEALDER_API_PORT:12581,
		VERSION:'20161227',
		APP_WEB:'http://fir.im/2f17',
	};
};

//大厅服配置
export function hall_server():HallServerConfig{
	return {
		HALL_IP:HALL_IP,
		CLEINT_PORT:HALL_CLIENT_PORT,
		FOR_ROOM_IP:LOCAL_IP,
		ROOM_PORT:HALL_ROOM_PORT,
		ACCOUNT_PRI_KEY:ACCOUNT_PRI_KEY,
		ROOM_PRI_KEY:ROOM_PRI_KEY
	};
};

//游戏服配置
export function game_server():GameServerConfig{
	return {
		SERVER_ID:"001",
		
		//暴露给大厅服的HTTP端口号
		HTTP_PORT:9003,
		//HTTP TICK的间隔时间，用于向大厅服汇报情况
		HTTP_TICK_TIME:5000,
		//大厅服IP
		HALL_IP:LOCAL_IP,
		FOR_HALL_IP:LOCAL_IP,
		//大厅服端口
		HALL_PORT:HALL_ROOM_PORT,
		//与大厅服协商好的通信加密KEY
		ROOM_PRI_KEY:ROOM_PRI_KEY,
		
		//暴露给客户端的接口
		CLIENT_IP:HALL_IP,
		CLIENT_PORT:10000,
	};
};

// 编译期自检：本文件的导出面必须满足 types/config.ts 的 ServerConfigs 契约
// （字段名或类型不一致时，下面这行会直接报"不满足约束"）。
// 只存在于类型空间，编译后不产生任何运行时代码。
type AssertExtends<T extends U, U> = T;
type _ExportsMatchServerConfigs = AssertExtends<{
	mysql:typeof mysql;
	account_server:typeof account_server;
	hall_server:typeof hall_server;
	game_server:typeof game_server;
},ServerConfigs>;
