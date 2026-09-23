var crypto = require('crypto');

exports.md5 = function (content) {
	var md5 = crypto.createHash('md5');
	md5.update(content);
	return md5.digest('hex');	
}

exports.toBase64 = function(content){
	//使用 Buffer.from；new Buffer() 在当前 Node 上会打印弃用告警
	return Buffer.from(content, 'utf8').toString('base64');
}

exports.fromBase64 = function(content){
	return Buffer.from(content, 'base64').toString('utf8');
}
