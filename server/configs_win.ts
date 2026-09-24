import type {
	AccountServerConfig,
	BanCheckConfig,
	GameServerConfig,
	HallServerConfig,
	MysqlConfig,
	ServerConfigs,
} from "./types/config";

var HALL_IP = "127.0.0.1";
var HALL_CLIENT_PORT = 9001;
var HALL_ROOM_PORT = 9002;

var ACCOUNT_PRI_KEY = "^&*#$%()@";
var ROOM_PRI_KEY = "~!@#$(*&^%$&";

//封禁校验的共享密钥。**必须与 platform_server 的 PLATFORM_INTERNAL_KEY 一致**：
//不一致时游戏服是 fail-open（照常放行）并打警告日志，表现为"封禁静默失效"。
//生产必须换成随机长串，并同时更新平台侧的环境变量。
var BAN_CHECK_PRI_KEY = "scmj-ban-check-dev-key";

//管理平台（platform_server）的地址——封禁校验就打在它身上。
var PLATFORM_IP = "127.0.0.1";
var PLATFORM_PORT = 8000;

var LOCAL_IP = 'localhost';

export function mysql():MysqlConfig{
	return {
		HOST:'127.0.0.1',
		USER:'root',
		PSWD:'',
		DB:'db_babykylin',
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

//封禁校验配置（大厅服与游戏服都用它）
export function ban_check():BanCheckConfig{
	//游戏服在登录 / 进房前调管理平台的内部只读接口，问这个玩家有没有被封：
	//  * PRI_KEY 与 platform_server 的 PLATFORM_INTERNAL_KEY 必须逐字一致；
	//  * 超时 / 连不上 / 平台报错一律 fail-open 放行并打警告日志——
	//    管理后台挂掉不该让全体玩家登不上游戏；
	//  * CACHE_TTL_MS 决定"后台点了封禁"到"玩家被拦下"的最大延迟。
	//平台没部署时把 ENABLE 设为 false，连 HTTP 请求都不会发。
	return {
		ENABLE:true,
		HOST:PLATFORM_IP,
		PORT:PLATFORM_PORT,
		PRI_KEY:BAN_CHECK_PRI_KEY,
		TIMEOUT_MS:1000,
		CACHE_TTL_MS:30000,
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
	ban_check:typeof ban_check;
},ServerConfigs>;
