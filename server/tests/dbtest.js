// 2016 年的手工脚本，参数与库名都是当时的值，仅用于随手连库看看（不是测试）。
// 驱动跟着 db.js 一起换成 mysql2：mysql 已从依赖里移除。
var mysql = require('mysql2');
var conn = mysql.createConnection({
    host: 'localhost',
    user: 'root',
    password: '',
    database:'nodejs',
    port: 3306
});
conn.connect();
conn.query('SELECT * FROM account', function(err, rows, fields) {
    if (err) throw err;
    console.log('The solution is: ', rows[0].account);
});
conn.end();