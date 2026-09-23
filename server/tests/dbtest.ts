// 2016 年的手工脚本，参数与库名都是当时的值，仅用于随手连库看看（不是测试）。
// 驱动跟着 db.js 一起换成 mysql2：mysql 已从依赖里移除。
// 迁移说明：`require('mysql2')` 换成 ESM 的 import，tsc 仍编译回 CommonJS 的 require，语义不变。
import * as mysql from "mysql2";

// 查询结果的行结构按 types/db_rows.ts 的 AccountRow 描述（这里只读 account 一列）。
import type { AccountRow } from "../types/db_rows";
var conn = mysql.createConnection({
    host: 'localhost',
    user: 'root',
    password: '',
    database:'nodejs',
    port: 3306
});
conn.connect();
conn.query('SELECT * FROM account', function(err: mysql.QueryError | null, rows: mysql.RowDataPacket[], fields: mysql.FieldPacket[]) {
    if (err) throw err;
    // 老脚本读的是 rows[0].account；这里断言成 AccountRow 后取的是同一个值。
    var row = rows[0] as AccountRow;
    console.log('The solution is: ', row.account);
});
conn.end();