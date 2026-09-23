// `export {}` 只用于把本文件标记成 TS 模块：否则顶层 var 会进入全局作用域，
// 与 tests/ 下其它脚本的同名变量（如 test.js / test2.js 的 `var t`）冲突。
// 它不导出任何运行时值，脚本的运行行为不变。
export {};

var m = {
	'k':'asdf',
}

var k: object = {};

// 原脚本是 `console.log(k == {})`。两侧直接比较对象字面量时 tsc 会以 TS2839 报错
//（“对象按引用比较，恒为 false”），故给右侧字面量加一次 unknown 断言；运行时表达式不变。
console.log(k == ({} as unknown));

var k: object = [1,2,3,4];
for(var t in k){
	console.log(t);
}