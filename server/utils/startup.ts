/**
 * 三个进程共用的启动横幅。
 *
 * 背景：原先每个 start() 都在自己的 app.listen() 之后立刻 console.log 一行
 * "xxx is listening on ..."。这有两个问题：
 *
 *   1. listen() 是异步的。端口被占用（EADDRINUSE）时那行提示照样打印，看上去
 *      "启动成功"，进程随后却带着一整屏堆栈崩掉，误导性很强；
 *   2. 一个进程其实监听多个端口（账号服 2 个、大厅服 2 个、游戏服 2 个），
 *      提示分散成多行，读不出"一个进程整体是否就绪"。
 *
 * 现在改为：各 start() 返回 http.Server，由 app.js 汇总后交给本模块。只有所有端点
 * 都真正进入 listening 才打印一次横幅；任一端口失败就打印原因并以非 0 退出。
 *
 * 输出不用 ANSI 颜色：start_all*.sh 走 nohup，颜色码只会污染 nohup.out。
 *
 * 迁移说明：横幅里的每一行文本、端口未监听/被占用时的提示与退出码都保持逐字不变；
 * `start_all_mac.sh` 的 `pid_matches_log()` 靠 `": PID <数字>"` 这一行核对进程身份，
 * 所以 `'进程     : PID ' + process.pid` 的写法一个字都不能动。
 */

import * as http from 'node:http';
import * as os from 'node:os';

/** 本次进程汇总的一个监听端点。 */
export interface StartupEndpoint {
	/** 该端点的 server，由各 service 的 start() 返回。 */
	server: http.Server;
	/** 端点名称，横幅里左对齐成一列。 */
	label: string;
	/** URL 协议，例如 "http"。 */
	scheme: string;
	/** 监听地址（通配地址会在展示时换成回环地址）。 */
	host: string;
	/** 配置里的端口；实际端口以 server.address() 为准。 */
	port: number;
	/** 可选的补充说明，追加在 URL 之后。 */
	note?: string;
}

/**
 * 启动横幅只用到 db 模块的 `ping` 这一个方法，所以这里用**最小接口**描述它，
 * 不为了类型方便去改 utils/db.ts 的导出面。
 *
 * `db.ping(callback)` 做一次 `SELECT 1`：成功回调 `(true)`，失败回调 `(false, 原因)`。
 */
export interface StartupDb {
	ping(callback: (ok: boolean, detail?: string) => void): void;
}

/** `report()` 的入参。 */
export interface StartupReportOptions {
	/** 进程名，例如 "账号服 (account_server)"。 */
	title: string;
	/** 启动时传入的配置文件（process.argv[2]）。 */
	configFile?: string;
	/** 横幅底部的提示语。 */
	note: string;
	/** 本次进程汇总的所有监听端点。 */
	endpoints: StartupEndpoint[];
	/** db 模块；传入则在横幅里附带一次数据库连通性自检。 */
	db?: StartupDb;
	/** 自检目标描述，例如 "db_scmj@127.0.0.1:3306"。 */
	dbLabel?: string;
}

/** 数据库自检结果：成功时没有附加说明，失败时带一行原因。 */
type DbStatus = { ok: true } | { ok: false; detail: string };

// 横幅最小宽度（以终端显示列计）
var MIN_WIDTH = 60;

// 端点名称的列宽
var LABEL_WIDTH = 20;

// 数据库自检的最长等待时间：MySQL 不可达时不能让横幅一直不出现
var DB_PING_TIMEOUT = 2000;

function repeat(ch:string,count:number):string{
	var s = '';
	for(var i = 0; i < count; ++i){
		s += ch;
	}
	return s;
}

// 中文（CJK）在终端里占两列。不按显示宽度算，右侧竖条就会参差不齐。
function displayWidth(str:string):number{
	var width = 0;
	for(var i = 0; i < str.length; ++i){
		// 0x2E80 起是 CJK 部首、汉字与全角标点
		width += str.charCodeAt(i) > 0x2E80 ? 2 : 1;
	}
	return width;
}

function padEnd(str:string,width:number):string{
	var diff = width - displayWidth(str);
	return diff > 0 ? (str + repeat(' ',diff)) : str;
}

function two(n:number):string{
	return n < 10 ? ('0' + n) : ('' + n);
}

function timestamp():string{
	var d = new Date();
	return d.getFullYear() + '-' + two(d.getMonth() + 1) + '-' + two(d.getDate())
		+ ' ' + two(d.getHours()) + ':' + two(d.getMinutes()) + ':' + two(d.getSeconds());
}

// 通配地址（0.0.0.0 / ::）不能直接当 URL 用，换成能点开的回环地址
function displayHost(host:string):string{
	if(host == null || host === '' || host === '0.0.0.0' || host === '::'){
		return '127.0.0.1';
	}
	return host;
}

// 用 server.address() 的实际端口，而不是配置里的端口：
// 配置写 0（随机端口）时只有前者才是真的。
//
// 老代码写的是 `(addr && addr.port)`：addr 为 null（还没监听）或为字符串（unix socket）
// 时回退到配置端口，端口为 0 时同样回退。这里补上 `typeof addr !== 'string'` 只是为了让
// 类型收窄到 AddressInfo，判定结果与老代码完全一致。
function endpointUrl(ep:StartupEndpoint):string{
	var addr = ep.server.address();
	var port = (addr && typeof addr !== 'string' && addr.port) ? addr.port : ep.port;
	return ep.scheme + '://' + displayHost(ep.host) + ':' + port;
}

function endpointPort(ep:StartupEndpoint):number{
	var addr = ep.server.address();
	return (addr && typeof addr !== 'string' && addr.port) ? addr.port : ep.port;
}

function box(title:string,rows:(string|null)[],width:number):string{
	var bar = repeat('=',width);
	var thin = ' ' + repeat('-',width - 2) + ' ';
	var out = ['',bar,' ' + title,bar];
	for(var i = 0; i < rows.length; ++i){
		var row = rows[i];
		if(row === null){
			out.push(thin);
			continue;
		}
		out.push(' ' + padEnd(row,width - 2) + ' ');
	}
	out.push(bar,'');
	return out.join('\n');
}

function printBanner(options:StartupReportOptions,dbStatus:DbStatus):void{
	var endpoints = options.endpoints;

	var rows:(string|null)[] = [];
	rows.push('状态     : 启动成功');
	rows.push('进程     : PID ' + process.pid);
	rows.push('运行环境 : ' + os.type() + ' ' + os.arch() + ', Node ' + process.version);
	rows.push('配置文件 : ' + (options.configFile == null ? '(未指定)' : options.configFile));
	rows.push('启动时间 : ' + timestamp());
	rows.push(null);

	var titleLine = '幼麟四川麻将 · ' + options.title;
	var width = displayWidth(titleLine) + 2;

	for(var i = 0; i < endpoints.length; ++i){
		var ep = endpoints[i];
		var row = padEnd(ep.label,LABEL_WIDTH) + ' ' + endpointUrl(ep);
		if(ep.note){
			row += '   ' + ep.note;
		}
		rows.push(row);
	}

	if(options.db){
		rows.push(null);
		rows.push(dbStatus.ok
			? ('数据库   : 连接正常 (' + options.dbLabel + ')')
			: ('数据库   : 不可用 — ' + dbStatus.detail + '（服务继续启动，相关接口会失败）'));
	}

	rows.push(null);
	rows.push(options.note);

	for(var j = 0; j < rows.length; ++j){
		// 取到局部变量只是为了收窄类型（分隔行是 null）；判定与老代码一致
		var line = rows[j];
		if(line !== null && displayWidth(line) + 2 > width){
			width = displayWidth(line) + 2;
		}
	}
	if(width < MIN_WIDTH){
		width = MIN_WIDTH;
	}

	console.log(box(titleLine,rows,width));
}

/**
 * 取错误的 `code`（Node 的 errno 错误带这个字段，TypeScript 的 `Error` 里没有）。
 * 与老代码一致：只认字符串形态的 code，没有就返回 undefined。
 */
function errorCode(err:Error):string|undefined{
	if('code' in err){
		var code:unknown = err.code;
		if(typeof code === 'string'){
			return code;
		}
	}
	return undefined;
}

function printFailure(options:StartupReportOptions,ep:StartupEndpoint,err:Error):void{
	var lines:string[] = [];
	lines.push('');
	lines.push('启动失败：' + options.title);
	lines.push('  端点     : ' + ep.label);
	lines.push('  地址     : ' + endpointUrl(ep));
	// 老代码是 `(err && err.code) ? err.code + ' ' : ''` + `(err && err.message) ? err.message : err`
	var code = (err ? errorCode(err) : undefined);
	lines.push('  错误     : ' + (code ? code + ' ' : '') + ((err && err.message) ? err.message : err));
	if(err && code === 'EADDRINUSE'){
		lines.push('  处理建议 : 端口已被占用。先执行 lsof -i :' + endpointPort(ep) + ' 找到并停掉占用进程，');
		lines.push('             或修改配置文件 ' + options.configFile + ' 里的端口。');
	}
	lines.push('  配置文件 : ' + options.configFile);
	lines.push('');
	console.error(lines.join('\n'));
	process.exit(1);
}

/**
 * 汇总本次进程的所有监听端点，全部就绪后打印启动横幅。
 *
 * @param {Object} options
 * @param {string} options.title      进程名，例如 "账号服 (account_server)"
 * @param {string} options.configFile 启动时传入的配置文件（process.argv[2]）
 * @param {string} options.note       横幅底部的提示语
 * @param {Array}  options.endpoints  形如 {server,label,scheme,host,port,note}
 * @param {Object} [options.db]       db 模块；传入则在横幅里附带一次数据库连通性自检
 * @param {string} [options.dbLabel]  自检目标描述，例如 "db_scmj@127.0.0.1:3306"
 *
 * 参数形状见 StartupReportOptions / StartupEndpoint。
 */
export function report(options:StartupReportOptions):void{
	var endpoints = options.endpoints || [];
	var remaining = endpoints.length;
	var settled = false;

	function finish():void{
		if(settled){
			return;
		}
		settled = true;

		var db = options.db;
		if(db == null || typeof db.ping !== 'function'){
			printBanner(options,{ok:true});
			return;
		}

		// 自检最多等 DB_PING_TIMEOUT，超时就按"未确认"处理，不拖住启动
		var answered = false;
		var timer = setTimeout(function(){
			if(answered){
				return;
			}
			answered = true;
			printBanner(options,{ok:false,detail:'连接自检超时 ' + DB_PING_TIMEOUT + 'ms'});
		},DB_PING_TIMEOUT);

		db.ping(function(ok,detail){
			if(answered){
				return;
			}
			answered = true;
			clearTimeout(timer);
			printBanner(options,{ok:ok,detail:detail || '未知错误'});
		});
	}

	function onListening():void{
		remaining -= 1;
		if(remaining <= 0){
			finish();
		}
	}

	for(var i = 0; i < endpoints.length; ++i){
		(function(ep:StartupEndpoint){
			ep.server.on('error',function(err){
				printFailure(options,ep,err);
			});
			// listen() 是异步的，这里同步挂监听即可拿到紧随其后的 listening。
			// 万一 server 已经在监听（例如被重复 start），直接计数，避免永远等不到事件。
			if(ep.server.listening){
				onListening();
			}
			else{
				ep.server.once('listening',onListening);
			}
		})(endpoints[i]);
	}
}
