var http = require('http');
var https = require('https');
var qs = require('querystring');

String.prototype.format = function(args) {
	var result = this;
	if (arguments.length > 0) {
		if (arguments.length == 1 && typeof (args) == "object") {
			for (var key in args) {
				if(args[key]!=undefined){
					var reg = new RegExp("({" + key + "})", "g");
					result = result.replace(reg, args[key]);
				}
			}
		}
		else {
			for (var i = 0; i < arguments.length; i++) {
				if (arguments[i] != undefined) {
					//var reg = new RegExp("({[" + i + "]})", "g");//这个在索引大于9时会有问题，谢谢何以笙箫的指出
					var reg = new RegExp("({)" + i + "(})", "g");
					result = result.replace(reg, arguments[i]);
				}
			}
		}
	}
	return result;
};

exports.post = function (host,port,path,data,callback) {
	
	var content = qs.stringify(data);  
	var options = {  
		hostname: host,  
		port: port,  
		path: path + '?' + content,  
		method:'GET'
	};  
	  
	var req = http.request(options, function (res) {  
		console.log('STATUS: ' + res.statusCode);  
		console.log('HEADERS: ' + JSON.stringify(res.headers));  
		res.setEncoding('utf8');  
		res.on('data', function (chunk) {  
			//console.log('BODY: ' + chunk);
			callback(chunk);
		});  
	});
	  
	req.on('error', function (e) {  
		console.log('problem with request: ' + e.message);  
	});  
	  
	req.end(); 
};

// 把请求错误写成"哪台机器、哪个端口、哪个路径、什么错误"。
// 直接用 e.message 是不够的：Node 对 localhost 会同时尝试 ::1 与 127.0.0.1，
// 两个都失败时抛出的是 message 为空的 AggregateError，日志里只剩 "problem with request: "，
// 完全看不出到底连不上谁（游戏服每秒向大厅服心跳，日志会被这种空行刷屏）。
function describeError(e,host,port,path){
	var code = (e && e.code) ? e.code : ((e && e.message) ? e.message : 'unknown error');
	return code + ' — ' + host + ':' + (port || '') + path;
}

exports.get2 = function (url,data,callback,safe) {
	var content = qs.stringify(data);
	var url = url + '?' + content;
	var proto = http;
	if(safe){
		proto = https;
	}
	var req = proto.get(url, function (res) {  
		//console.log('STATUS: ' + res.statusCode);  
		//console.log('HEADERS: ' + JSON.stringify(res.headers));  
		res.setEncoding('utf8');  
		res.on('data', function (chunk) {  
			//console.log('BODY: ' + chunk);
			var json = JSON.parse(chunk);
			callback(true,json);
		});  
	});
	  
	req.on('error', function (e) {  
		console.log('problem with request: ' + ((e && e.code) ? e.code : e.message) + ' — ' + url);
		callback(false,e);
	});  
	  
	req.end(); 
};

exports.get = function (host,port,path,data,callback,safe) {
	var content = qs.stringify(data);  
	var options = {  
		hostname: host,  
		path: path + '?' + content,  
		method:'GET'
	};
	if(port){
		options.port = port;
	}
	var proto = http;
	if(safe){
		proto = https;
	}
	var req = proto.request(options, function (res) {  
		//console.log('STATUS: ' + res.statusCode);  
		//console.log('HEADERS: ' + JSON.stringify(res.headers));  
		res.setEncoding('utf8');  
		res.on('data', function (chunk) {  
			//console.log('BODY: ' + chunk);
			var json = JSON.parse(chunk);
			callback(true,json);
		});  
	});
	  
	req.on('error', function (e) {  
		console.log('problem with request: ' + describeError(e,host,port,path));
		callback(false,e);
	});  
	  
	req.end(); 
};

// 拉取一个 URL 的原始响应体，结果通过 callback(contentType,body) 返回；失败时两个参数都是 null。
//
// 这里原先叫 getSync()：用 fibers 把异步 HTTP 包装成同步调用（fibers.yield / fiber.run）。
// 但 fibers 1.0.15 的原生模块只支持到 node 8 左右，在 Node 12+ 与 Apple Silicon 上根本编译不出来，
// require('fibers') 直接抛 "Missing binary"，导致三个进程连启动都做不到。
// 因此改回与其它导出函数一致的回调风格，调用方按异步写法处理（见 account_server.js 的 /image）。
exports.getRaw = function (url,data,safe,encoding,callback) {
	var content = qs.stringify(data);
	// data 为空时不要拼出多余的 '?'
	var reqUrl = content ? (url + '?' + content) : url;

	var proto = http;
	if(safe){
		proto = https;
	}

	if(!encoding){
		encoding = 'utf8';
	}

	// end 与 error 在异常链路上可能都会触发，保证回调只走一次
	var done = false;
	function finish(type,body){
		if(done){
			return;
		}
		done = true;
		callback(type,body);
	}

	var req = proto.get(reqUrl, function (res) {
		//console.log('STATUS: ' + res.statusCode);
		//console.log('HEADERS: ' + JSON.stringify(res.headers));
		res.setEncoding(encoding);
		var body = '';
		var type = res.headers["content-type"];

		res.on('data', function (chunk) {
			body += chunk;
		});

		res.on('end',function(){
			if(encoding != 'binary'){
				try {
					finish(type,JSON.parse(body));
				} catch(e) {
					// 老实现解析失败时没有唤醒 fiber，调用方会一直挂住；现在明确按失败返回
					console.log('JSON parse error: ' + e + ', url: ' + reqUrl);
					finish(null,null);
				}
			}
			else{
				finish(type,body);
			}
		});
	});

	req.on('error', function (e) {
		console.log('problem with request: ' + ((e && e.code) ? e.code : e.message) + ' — ' + reqUrl);
		finish(null,null);
	});

	req.end();
};

exports.send = function(res,errcode,errmsg,data){
	if(data == null){
		data = {};
	}
	data.errcode = errcode;
	data.errmsg = errmsg;
	var jsonstr = JSON.stringify(data);
	res.send(jsonstr);
};