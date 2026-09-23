// 驱动用 mysql2 而不是 mysql：两者 API 兼容（本文件只用到 createPool/getConnection/query/release），
// 但 mysql@2.x 只支持 mysql_native_password，连不上 MySQL 8 默认的 caching_sha2_password，
// 在 brew 装的 MySQL 8.4 上会直接报 ER_NOT_SUPPORTED_AUTH_MODE。详见 server/AGENTS.md §1.1。
import * as mysql from "mysql2";
import type { FieldPacket, QueryError, QueryResult, ResultSetHeader } from "mysql2";

// 本文件有 11 处 `sql.format(...)`，依赖 http.ts 顶部挂到 String.prototype 上的补丁。
// 迁移前这是隐式依赖（靠 db.js 与 http.js 谁先被 require），这里显式引入把加载顺序钉死，
// 避免以后有人调整 import 顺序时把 `sql.format` 弄丢。
import "./http";

import * as crypto from "./crypto";

import type { MysqlConfig } from "../types/config";
import type {
    AccountRow,
    GameRow,
    MessageRow,
    RoomAddrRow,
    RoomRow,
    UserBaseInfoRow,
    UserBriefRow,
    UserRow,
} from "../types/db_rows";
import type { RoomConf } from "../types/domain";

// 行结构契约在 types/db_rows.ts；这里再导出一次，调用方从 db 或 types/db_rows 引入都行。
export type {
    AccountRow,
    GameRow,
    MessageRow,
    RoomAddrRow,
    RoomRow,
    UserBaseInfoRow,
    UserBriefRow,
    UserRow,
} from "../types/db_rows";

/**
 * 直接拼进 SQL 的入参（账号、userid、房间号、游戏序号…）。
 *
 * 老代码一律用 `'...' + value` 拼串、从不解析：调用方既有游戏服内部的 number，
 * 也有 `req.query` 边界的 string / number / boolean / null / undefined。
 * 这里如实描述这个联合——在 db 层补 parseInt 或存在性判断会改变 SQL 文本（也就改变了行为）。
 */
type SqlValue = string | number | boolean | null | undefined;

/**
 * db 回调里的错误。
 *
 * 两个来源：连接池 `getConnection` 的 Node `ErrnoException`（`code` 可选）与 `conn.query`
 * 的 mysql2 `QueryError`（`code` 必有）。老代码正是靠 `err.code`（如 `ER_DUP_ENTRY`）判断，
 * 这里取两者的公共最小面。
 */
interface DbError extends Error {
    code?: string;
}

/**
 * `query` 的回调：与迁移前的 `(err, vals, fields)` 实参个数、顺序一致。
 *
 * `rows` 保留 mysql2 的联合结果类型（SELECT 是行数组，写操作是 `ResultSetHeader`），
 * 由各调用方按自己的 SQL 收窄成 `types/db_rows.ts` 里的行接口；`fields` 在出错分支为 null。
 */
export type QueryCallback = (
    err: DbError | null,
    rows: QueryResult | null,
    fields: FieldPacket[] | null,
) => void;

/** `get_gems` 的投影：只取 gems 一列（从 UserRow 派生，不新造字段）。 */
type GemsRow = Pick<UserRow, "gems">;
/** `get_user_history` 的投影：只取 history 一列。 */
type HistoryRow = Pick<UserRow, "history">;
/** `is_user_exist` 的投影：只取 userid 一列。 */
type UserIdRow = Pick<UserRow, "userid">;
/** `get_room_id_of_user` 的投影：只取 roomid 一列。 */
type RoomIdRow = Pick<UserRow, "roomid">;
/** `get_room_uuid` 的投影：只取 uuid 一列。 */
type RoomUuidRow = Pick<RoomRow, "uuid">;
/** `get_games_of_room` 的投影：game_index / create_time / result 三列。 */
type GameListRow = Pick<GameRow, "game_index" | "create_time" | "result">;
/** `get_detail_of_game` 的投影：base_info / action_records 两列。 */
type GameDetailRow = Pick<GameRow, "base_info" | "action_records">;

/**
 * 写操作（UPDATE / DELETE）的执行结果。
 *
 * mysql2 返回 `ResultSetHeader`，它**没有** `length`；而老代码在 `update_user_history`、
 * `cost_gems`、`set_room_id_of_user` 三处对它读 `length`，运行时取到的是 `undefined`
 * （于是 `undefined == 0`、`undefined > 0` 都为假）。这是既有行为，迁移里原样保留；
 * 类型上补一个 `length` 只是如实描述"这里读了一个运行时并不存在的属性"，不加任何运行时判断。
 */
type ExecResult = ResultSetHeader & { length: number };

var pool: mysql.Pool | null = null;

/**
 * 占位回调。
 *
 * 老代码用 `callback == null ? nop : callback` 给可选回调兜底；原实现是 7 个未使用的形参，
 * 这里写成可选参数只是让它能赋给任意形态的回调类型，运行时依旧"什么都不做"。
 */
function nop(a?: unknown,b?: unknown,c?: unknown,d?: unknown,e?: unknown,f?: unknown,g?: unknown): void {

}
  
function generateUserId(): string {
    var Id = "";
    for (var i = 0; i < 6; ++i) {
        if (i > 0) {
            Id += Math.floor(Math.random() * 10);
        } else {
            Id += Math.floor(Math.random() * 9) + 1;
        }
    }
    return Id;
}

function query(sql: string,callback: QueryCallback): void {
    // init 之前 pool 为 null，原实现就是在这里抛 TypeError；非空断言只为通过严格空检查，
    // 不新增 `if(pool == null)` 保护，抛错行为保持不变。
    pool!.getConnection(function(err,conn){
        if(err){
            callback(err,null,null);
        }else{
            conn.query(sql,function(qerr: QueryError | null,vals: QueryResult,fields: FieldPacket[]){
                //释放连接
                conn.release();
                //事件驱动回调
                callback(qerr,vals,fields);
            });
        }
    });
};

export function init(config: MysqlConfig): void {
    pool = mysql.createPool({
        host: config.HOST,
        user: config.USER,
        password: config.PSWD,
        database: config.DB,
        port: config.PORT,
    });
};

// 启动自检：探测数据库是否真的连得上，供启动横幅显示真实状态。
// 只做一次 SELECT 1，不改变连接池状态；探测失败不抛异常、也不要求进程退出——
// /guest 等接口并不依赖数据库，进程仍应能对外服务。
export function ping(callback?: (ok: boolean,detail?: string) => void): void {
    callback = callback == null? nop:callback;
    if(pool == null){
        callback(false,"db.init() 尚未调用");
        return;
    }
    pool.getConnection(function(err,conn){
        if(err){
            callback(false,err.code || err.message);
            return;
        }
        conn.query('SELECT 1',function(qerr: DbError | null){
            conn.release();
            if(qerr){
                callback(false,qerr.code || qerr.message);
                return;
            }
            callback(true);
        });
    });
};

export function is_account_exist(account: SqlValue,callback?: (exist: boolean) => void): void {
    callback = callback == null? nop:callback;
    if(account == null){
        callback(false);
        return;
    }

    var sql = 'SELECT * FROM t_accounts WHERE account = "' + account + '"';
    query(sql, function(err, rows, fields) {
        if (err) {
            callback(false);
            throw err;
        }
        else{
            // SELECT *：mysql2 返回 RowDataPacket[]，按 db_rows.ts 的契约断言成 t_accounts 行结构
            // （t_accounts 只有 account / password 两列，不会少字段）。
            var accounts = rows as AccountRow[];
            if(accounts.length > 0){
                callback(true);
            }
            else{
                callback(false);
            }
        }
    });
};

export function create_account(account: SqlValue,password: string | null | undefined,callback?: (ok: boolean) => void): void {
    callback = callback == null? nop:callback;
    if(account == null || password == null){
        callback(false);
        return;
    }

    // password 走 md5，必须先收窄成 string（原实现同样只判了 null）。
    var psw = crypto.md5(password);
    var sql = 'INSERT INTO t_accounts(account,password) VALUES("' + account + '","' + psw + '")';
    query(sql, function(err, rows, fields) {
        if (err) {
            if(err.code == 'ER_DUP_ENTRY'){
                callback(false);
                return;         
            }
            callback(false);
            throw err;
        }
        else{
            callback(true);            
        }
    });
};

export function get_account_info(account: SqlValue,password: string | null | undefined,callback?: (account: AccountRow | null) => void): void {
    callback = callback == null? nop:callback;
    if(account == null){
        callback(null);
        return;
    }  

    var sql = 'SELECT * FROM t_accounts WHERE account = "' + account + '"';
    query(sql, function(err, rows, fields) {
        if (err) {
            callback(null);
            throw err;
        }

        // SELECT *：断言成 t_accounts 行结构。
        var accounts = rows as AccountRow[];

        if(accounts.length == 0){
            callback(null);
            return;
        }
        
        if(password != null){
            var psw = crypto.md5(password);
            if(accounts[0].password == psw){
                callback(null);
                return;
            }    
        }

        callback(accounts[0]);
    }); 
};

export function is_user_exist(account: SqlValue,callback?: (exist: boolean) => void): void {
    callback = callback == null? nop:callback;
    if(account == null){
        callback(false);
        return;
    }

    var sql = 'SELECT userid FROM t_users WHERE account = "' + account + '"';
    query(sql, function(err, rows, fields) {
        if (err) {
            throw err;
        }

        // SELECT userid：断言成 UserRow 的 userid 投影。
        var users = rows as UserIdRow[];

        if(users.length == 0){
            callback(false);
            return;
        }

        callback(true);
    });  
}


export function get_user_data(account: SqlValue,callback?: (user: UserBriefRow | null) => void): void {
    callback = callback == null? nop:callback;
    if(account == null){
        callback(null);
        return;
    }

    var sql = 'SELECT userid,account,name,lv,exp,coins,gems,roomid FROM t_users WHERE account = "' + account + '"';
    query(sql, function(err, rows, fields) {
        if (err) {
            callback(null);
            throw err;
        }

        // 显式 SELECT 的那几列正对应 UserBriefRow（不含 history，见 db_rows.ts 的说明）。
        var users = rows as UserBriefRow[];

        if(users.length == 0){
            callback(null);
            return;
        }
        // t_users.name 允许 NULL；原实现直接把可能为 null 的值交给 fromBase64（为 null 时抛错），
        // 断言只为通过类型检查，行为不变。
        users[0].name = crypto.fromBase64(users[0].name as string);
        callback(users[0]);
    });
};

export function get_user_data_by_userid(userid: SqlValue,callback?: (user: UserBriefRow | null) => void): void {
    callback = callback == null? nop:callback;
    if(userid == null){
        callback(null);
        return;
    }

    var sql = 'SELECT userid,account,name,lv,exp,coins,gems,roomid FROM t_users WHERE userid = ' + userid;
    query(sql, function(err, rows, fields) {
        if (err) {
            callback(null);
            throw err;
        }

        // 同 get_user_data：断言成 UserBriefRow[]。
        var users = rows as UserBriefRow[];

        if(users.length == 0){
            callback(null);
            return;
        }
        // 同 get_user_data：name 可能为 NULL，断言只为通过类型检查。
        users[0].name = crypto.fromBase64(users[0].name as string);
        callback(users[0]);
    });
};

/**增加玩家房卡 */
export function add_user_gems(userid: SqlValue,gems: SqlValue,callback?: (ok: boolean) => void): void {
    callback = callback == null? nop:callback;
    if(userid == null){
        callback(false);
        return;
    }
    
    var sql = 'UPDATE t_users SET gems = gems +' + gems + ' WHERE userid = ' + userid;
    console.log(sql);
    query(sql,function(err,rows,fields){
        if(err){
            console.log(err);
            callback(false);
            return;
        }
        else{
            // UPDATE 返回 ResultSetHeader（没有 rows 数组），判据是 affectedRows。
            var result = rows as ResultSetHeader;
            callback(result.affectedRows > 0);
            return; 
        } 
    });
};

export function get_gems(account: SqlValue,callback?: (gems: GemsRow | null) => void): void {
    callback = callback == null? nop:callback;
    if(account == null){
        callback(null);
        return;
    }

    var sql = 'SELECT gems FROM t_users WHERE account = "' + account + '"';
    query(sql, function(err, rows, fields) {
        if (err) {
            callback(null);
            throw err;
        }

        // SELECT gems：断言成 UserRow 的 gems 投影。
        var users = rows as GemsRow[];

        if(users.length == 0){
            callback(null);
            return;
        }

        callback(users[0]);
    });
}; 

export function get_user_history(userId: SqlValue,callback?: (history: unknown[] | null) => void): void {
    callback = callback == null? nop:callback;
    if(userId == null){
        callback(null);
        return;
    }

    var sql = 'SELECT history FROM t_users WHERE userid = "' + userId + '"';
    query(sql, function(err, rows, fields) {
        if (err) {
            callback(null);
            throw err;
        }

        // SELECT history：断言成 UserRow 的 history 投影。
        var users = rows as HistoryRow[];

        if(users.length == 0){
            callback(null);
            return;
        }
        var history = users[0].history;
        if(history == null || history == ""){
            callback(null);    
        }
        else{
            console.log(history.length);
            // history 是写入方（gamemgr 的 store_history）自己定义的 JSON 数组，
            // types/db_rows.ts 没有为它建契约，解析结果按"元素未知的数组"处理。
            // 原实现复用 history 变量装解析结果，这里只多一个局部名，行为不变。
            var parsed = JSON.parse(history) as unknown[];
            callback(parsed);
        }        
    });
};

export function update_user_history(userId: SqlValue,history: unknown,callback?: (ok: boolean) => void): void {
    callback = callback == null? nop:callback;
    if(userId == null || history == null){
        callback(false);
        return;
    }

    history = JSON.stringify(history);
    var sql = 'UPDATE t_users SET roomid = null, history = \'' + history + '\' WHERE userid = "' + userId + '"';
    //console.log(sql);
    query(sql, function(err, rows, fields) {
        if (err) {
            callback(false);
            throw err;
        }

        // 老代码对 UPDATE 结果读 length（ResultSetHeader 上没这个属性，运行时是 undefined）：
        // `undefined == 0` 为假，因此实际总会走 callback(true)。断言成 ExecResult 只为描述该读法。
        var result = rows as ExecResult;

        if(result.length == 0){
            callback(false);
            return;
        }

        callback(true);
    });
};

export function get_games_of_room(room_uuid: SqlValue,callback?: (games: GameListRow[] | null) => void): void {
    callback = callback == null? nop:callback;
    if(room_uuid == null){
        callback(null);
        return;
    }

    var sql = 'SELECT game_index,create_time,result FROM t_games_archive WHERE room_uuid = "' + room_uuid + '"';
    //console.log(sql);
    query(sql, function(err, rows, fields) {
        if (err) {
            callback(null);
            throw err;
        }

        // 三列投影，从 GameRow 派生。
        var games = rows as GameListRow[];

        if(games.length == 0){
            callback(null);
            return;
        }

        callback(games);
    });
};

export function get_detail_of_game(room_uuid: SqlValue,index: SqlValue,callback?: (detail: GameDetailRow | null) => void): void {
    callback = callback == null? nop:callback;
    if(room_uuid == null || index == null){
        callback(null);
        return;
    }
    var sql = 'SELECT base_info,action_records FROM t_games_archive WHERE room_uuid = "' + room_uuid + '" AND game_index = ' + index ;
    //console.log(sql);
    query(sql, function(err, rows, fields) {
        if (err) {
            callback(null);
            throw err;
        }

        // 两列投影，从 GameRow 派生。
        var games = rows as GameDetailRow[];

        if(games.length == 0){
            callback(null);
            return;
        }
        callback(games[0]);
    });
}

export function create_user(account: string | null | undefined,name: string | null | undefined,coins: number,gems: number,sex: number,headimg: string | null | undefined,callback?: (ok: boolean) => void): void {
    callback = callback == null? nop:callback;
    if(account == null || name == null || coins==null || gems==null){
        callback(false);
        return;
    }
    // headimg 一律被拼成 SQL 字面量（有值加引号，没有则写 null 这个裸值），之后必然收窄成 string。
    if(headimg){
        headimg = '"' + headimg + '"';
    }
    else{
        headimg = 'null';
    }
    name = crypto.toBase64(name);
    var userId = generateUserId();

    var sql = 'INSERT INTO t_users(userid,account,name,coins,gems,sex,headimg) VALUES("{0}", "{1}","{2}",{3},{4},{5},{6})';
    sql = sql.format(userId,account,name,coins,gems,sex,headimg);
    console.log(sql);
    query(sql, function(err, rows, fields) {
        if (err) {
            throw err;
        }
        callback(true);
    });
};

export function update_user_info(userid: string | null | undefined,name: string,headimg: string | null | undefined,sex: number,callback?: (rows: QueryResult | null) => void): void {
    callback = callback == null? nop:callback;
    if(userid == null){
        callback(null);
        return;
    }
 
    // 同 create_user：headimg 拼成 SQL 字面量后收窄成 string。
    if(headimg){
        headimg = '"' + headimg + '"';
    }
    else{
        headimg = 'null';
    }
    name = crypto.toBase64(name);
    var sql = 'UPDATE t_users SET name="{0}",headimg={1},sex={2} WHERE account="{3}"';
    sql = sql.format(name,headimg,sex,userid);
    console.log(sql);
    query(sql, function(err, rows, fields) {
        if (err) {
            throw err;
        }
        // 原实现把查询结果原样回调（调用方都忽略这个参数），这里保留同样的实参。
        callback(rows);
    });
};

export function get_user_base_info(userid: string | number | null | undefined,callback?: (info: UserBaseInfoRow | null) => void): void {
    callback = callback == null? nop:callback;
    if(userid == null){
        callback(null);
        return;
    }
    var sql = 'SELECT name,sex,headimg FROM t_users WHERE userid={0}';
    sql = sql.format(userid);
    console.log(sql);
    query(sql, function(err, rows, fields) {
        if (err) {
            throw err;
        }
        // 三列正对应 UserBaseInfoRow；原实现不判空行，行不存在时会在下一行抛错（保持不动）。
        var users = rows as UserBaseInfoRow[];
        // name 允许 NULL，同 get_user_data：断言只为通过类型检查。
        users[0].name = crypto.fromBase64(users[0].name as string);
        callback(users[0]);
    });
};

export function is_room_exist(roomId: SqlValue,callback?: (exist: boolean) => void): void {
    callback = callback == null? nop:callback;
    var sql = 'SELECT * FROM t_rooms WHERE id = "' + roomId + '"';
    query(sql, function(err, rows, fields) {
        if(err){
            callback(false);
            throw err;
        }
        else{
            // SELECT *：断言成 t_rooms 行结构。
            var roomRows = rows as RoomRow[];
            callback(roomRows.length > 0);
        }
    });
};

export function cost_gems(userid: SqlValue,cost: SqlValue,callback?: (ok: boolean) => void): void {
    callback = callback == null? nop:callback;
    var sql = 'UPDATE t_users SET gems = gems -' + cost + ' WHERE userid = ' + userid;
    console.log(sql);
    query(sql, function(err, rows, fields) {
        if(err){
            callback(false);
            throw err;
        }
        else{
            // 同 update_user_history：UPDATE 结果没有 length，`undefined > 0` 恒为假（既有行为）。
            var result = rows as ExecResult;
            callback(result.length > 0);
        }
    });
};

export function set_room_id_of_user(userId: string | number,roomId: SqlValue,callback?: (ok: boolean) => void): void {
    callback = callback == null? nop:callback;
    if(roomId != null){
        roomId = '"' + roomId + '"';
    }
    var sql = 'UPDATE t_users SET roomid = '+ roomId + ' WHERE userid = "' + userId + '"';
    console.log(sql);
    query(sql, function(err, rows, fields) {
        if(err){
            console.log(err);
            callback(false);
            throw err;
        }
        else{
            // 同 cost_gems：UPDATE 结果没有 length，`undefined > 0` 恒为假（既有行为）。
            var result = rows as ExecResult;
            callback(result.length > 0);
        }
    });
};

export function get_room_id_of_user(userId: SqlValue,callback?: (roomId: string | null) => void): void {
    callback = callback == null? nop:callback;
    var sql = 'SELECT roomid FROM t_users WHERE userid = "' + userId + '"';
    query(sql, function(err, rows, fields) {
        if(err){
            callback(null);
            throw err;
        }
        else{
            // SELECT roomid：断言成 UserRow 的 roomid 投影。
            var users = rows as RoomIdRow[];
            if(users.length > 0){
                callback(users[0].roomid);
            }
            else{
                callback(null);
            }
        }
    });
};


export function create_room(roomId: string,conf: RoomConf,ip: string,port: number,create_time: number,callback?: (uuid: string | null) => void): void {
    callback = callback == null? nop:callback;
    var sql = "INSERT INTO t_rooms(uuid,id,base_info,ip,port,create_time) \
                VALUES('{0}','{1}','{2}','{3}',{4},{5})";
    var uuid = Date.now() + roomId;
    var baseInfo = JSON.stringify(conf);
    sql = sql.format(uuid,roomId,baseInfo,ip,port,create_time);
    console.log(sql);
    query(sql,function(err,row,fields){
        if(err){
            callback(null);
            throw err;
        }
        else{
            callback(uuid);
        }
    });
};

export function get_room_uuid(roomId: SqlValue,callback?: (uuid: string | null) => void): void {
    callback = callback == null? nop:callback;
    var sql = 'SELECT uuid FROM t_rooms WHERE id = "' + roomId + '"';
    query(sql,function(err,rows,fields){
        if(err){
            callback(null);
            throw err;
        }
        else{
            // SELECT uuid：断言成 RoomRow 的 uuid 投影；原实现不判空行，行不存在时会抛错（保持不动）。
            var roomRows = rows as RoomUuidRow[];
            callback(roomRows[0].uuid);
        }
    });
};

export function update_seat_info(roomId: string,seatIndex: number,userId: number,icon: string,name: string,callback?: (ok: boolean) => void): void {
    callback = callback == null? nop:callback;
    var sql = 'UPDATE t_rooms SET user_id{0} = {1},user_icon{0} = "{2}",user_name{0} = "{3}" WHERE id = "{4}"';
    name = crypto.toBase64(name);
    sql = sql.format(seatIndex,userId,icon,name,roomId);
    //console.log(sql);
    query(sql,function(err,row,fields){
        if(err){
            callback(false);
            throw err;
        }
        else{
            callback(true);
        }
    });
}

export function update_num_of_turns(roomId: string,numOfTurns: number,callback?: (ok: boolean) => void): void {
    callback = callback == null? nop:callback;
    var sql = 'UPDATE t_rooms SET num_of_turns = {0} WHERE id = "{1}"'
    sql = sql.format(numOfTurns,roomId);
    //console.log(sql);
    query(sql,function(err,row,fields){
        if(err){
            callback(false);
            throw err;
        }
        else{
            callback(true);
        }
    });
};


export function update_next_button(roomId: string,nextButton: number,callback?: (ok: boolean) => void): void {
    callback = callback == null? nop:callback;
    var sql = 'UPDATE t_rooms SET next_button = {0} WHERE id = "{1}"'
    sql = sql.format(nextButton,roomId);
    //console.log(sql);
    query(sql,function(err,row,fields){
        if(err){
            callback(false);
            throw err;
        }
        else{
            callback(true);
        }
    });
};

export function get_room_addr(roomId: SqlValue,callback?: (ok: boolean,ip: string | null,port: number | null) => void): void {
    callback = callback == null? nop:callback;
    if(roomId == null){
        callback(false,null,null);
        return;
    }

    var sql = 'SELECT ip,port FROM t_rooms WHERE id = "' + roomId + '"';
    query(sql, function(err, rows, fields) {
        if(err){
            callback(false,null,null);
            throw err;
        }
        // 两列正对应 RoomAddrRow。
        var addrs = rows as RoomAddrRow[];
        if(addrs.length > 0){
            callback(true,addrs[0].ip,addrs[0].port);
        }
        else{
            callback(false,null,null);
        }
    });
};

export function get_room_data(roomId: SqlValue,callback?: (room: RoomRow | null) => void): void {
    callback = callback == null? nop:callback;
    if(roomId == null){
        callback(null);
        return;
    }

    var sql = 'SELECT * FROM t_rooms WHERE id = "' + roomId + '"';
    query(sql, function(err, rows, fields) {
        if(err){
            callback(null);
            throw err;
        }
        // SELECT *：断言成 t_rooms 行结构。
        var roomRows = rows as RoomRow[];
        if(roomRows.length > 0){
            roomRows[0].user_name0 = crypto.fromBase64(roomRows[0].user_name0);
            roomRows[0].user_name1 = crypto.fromBase64(roomRows[0].user_name1);
            roomRows[0].user_name2 = crypto.fromBase64(roomRows[0].user_name2);
            roomRows[0].user_name3 = crypto.fromBase64(roomRows[0].user_name3);
            callback(roomRows[0]);
        }
        else{
            callback(null);
        }
    });
};

export function delete_room(roomId: string,callback?: (ok: boolean) => void): void {
    callback = callback == null? nop:callback;
    if(roomId == null){
        callback(false);
    }
    var sql = "DELETE FROM t_rooms WHERE id = '{0}'";
    sql = sql.format(roomId);
    console.log(sql);
    query(sql,function(err,rows,fields){
        if(err){
            callback(false);
            throw err;
        }
        else{
            callback(true);
        }
    });
}

export function create_game(room_uuid: string,index: number,base_info: string,callback?: (gameIndex: number | null) => void): void {
    callback = callback == null? nop:callback;
    var sql = "INSERT INTO t_games(room_uuid,game_index,base_info,create_time) VALUES('{0}',{1},'{2}',unix_timestamp(now()))";
    sql = sql.format(room_uuid,index,base_info);
    //console.log(sql);
    query(sql,function(err,rows,fields){
        if(err){
            callback(null);
            throw err;
        }
        else{
            // INSERT 返回 ResultSetHeader，insertId 就是自增主键。
            var result = rows as ResultSetHeader;
            callback(result.insertId);
        }
    });
};

export function delete_games(room_uuid: string,callback?: (ok: boolean) => void): void {
    callback = callback == null? nop:callback;
    if(room_uuid == null){
        callback(false);
    }    
    var sql = "DELETE FROM t_games WHERE room_uuid = '{0}'";
    sql = sql.format(room_uuid);
    console.log(sql);
    query(sql,function(err,rows,fields){
        if(err){
            callback(false);
            throw err;
        }
        else{
            callback(true);
        }
    });
}

export function archive_games(room_uuid: string,callback?: (ok: boolean) => void): void {
    callback = callback == null? nop:callback;
    if(room_uuid == null){
        callback(false);
    }
    var sql = "INSERT INTO t_games_archive(SELECT * FROM t_games WHERE room_uuid = '{0}')";
    sql = sql.format(room_uuid);
    console.log(sql);
    query(sql,function(err,rows,fields){
        if(err){
            callback(false);
            throw err;
        }
        else{
            delete_games(room_uuid,function(ret){
                callback(ret);
            });
        }
    });
}

export function update_game_action_records(room_uuid: string,index: number,actions: string,callback?: (ok: boolean) => void): void {
    callback = callback == null? nop:callback;
    var sql = "UPDATE t_games SET action_records = '"+ actions +"' WHERE room_uuid = '" + room_uuid + "' AND game_index = " + index ;
    //console.log(sql);
    query(sql,function(err,rows,fields){
        if(err){
            callback(false);
            throw err;
        }
        else{
            callback(true);
        }
    });
};

export function update_game_result(room_uuid: string,index: number,result: unknown,callback?: (ok: boolean) => void): void {
    callback = callback == null? nop:callback;
    if(room_uuid == null || result){
        callback(false);
    }
    
    result = JSON.stringify(result);
    var sql = "UPDATE t_games SET result = '"+ result +"' WHERE room_uuid = '" + room_uuid + "' AND game_index = " + index ;
    //console.log(sql);
    query(sql,function(err,rows,fields){
        if(err){
            callback(false);
            throw err;
        }
        else{
            callback(true);
        }
    });
};

export function get_message(type: SqlValue,version: SqlValue,callback?: (message: MessageRow | null) => void): void {
    callback = callback == null? nop:callback;
    
    var sql = 'SELECT * FROM t_message WHERE type = "'+ type + '"';
    
    if(version == "null"){
        version = null;
    }
    
    if(version){
        version = '"' + version + '"';
        sql += ' AND version != ' + version;   
    }
     
    query(sql, function(err, rows, fields) {
        if(err){
            // 原实现在查询失败时回调的是 boolean false（不是 null）——这是历史行为，不能改；
            // 对外契约仍按 `MessageRow | null` 描述（调用方都是判空后取 msg / version）。
            // 这里把 false 断言出去，传的值原样是 false，运行时不变。
            callback(false as unknown as MessageRow | null);
            throw err;
        }
        else{
            // SELECT *：断言成 t_message 行结构。
            var messages = rows as MessageRow[];
            if(messages.length > 0){
                callback(messages[0]);    
            }
            else{
                callback(null);
            }
        }
    });
};

export { query };
