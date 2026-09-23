// `export {}` 只用于把本文件标记成 TS 模块：否则顶层 var 会进入全局作用域，
// 与 tests/ 下其它脚本的同名变量（如 test.js / test2.js 的 `var t`）冲突。
// 它不导出任何运行时值，脚本的运行行为不变。
export {};

var t = new Uint8Array([1,2,3,4,5]);
console.log(t);
console.log(t.buffer);
// 老脚本演示的是 `1 == "1"` 的宽松相等（打印 true）。两侧都是字面量时 tsc 会以
// TS2367（number 与 string 没有重叠）报错，故给左侧加一次联合类型断言；运行时表达式不变。
console.log((1 as number | string) == "1");