// `export {}` 只用于把本文件标记成 TS 模块：否则顶层 var 会进入全局作用域，
// 与 tests/ 下其它脚本的同名变量（如 test.js / test2.js 的 `var t`）冲突。
// 它不导出任何运行时值，脚本的运行行为不变。
export {};

var account = "18081177883";
var password = 123456;

var sql = ' SELECT * FROM t_admins WHERE account = "' + account + '" AND password = PASSWORD("' + password + '")';
console.log(sql);
