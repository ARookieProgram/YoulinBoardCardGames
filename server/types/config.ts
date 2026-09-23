/**
 * 配置文件（configs_mac.ts / configs_win.ts）的类型契约。
 *
 * 配置是**函数式导出**的数据模块，三个进程都通过 `process.argv[2]` 指定要用哪一份：
 *
 *     node dist/game_server/app.js ../configs_mac.js
 *
 * 因此模块路径来自命令行，编译器无法静态解析，加载动作集中在 `utils/config.ts`
 * 里的一个函数中（见那里的说明）。这里只描述结构。
 */

/** MySQL 连接参数（`db.init` 的入参）。 */
export interface MysqlConfig {
  HOST: string;
  USER: string;
  PSWD: string;
  DB: string;
  PORT: number;
}

/** 账号服配置（:9000 客户端、:12581 渠道/代理）。 */
export interface AccountServerConfig {
  CLIENT_PORT: number;
  HALL_IP: string;
  HALL_CLIENT_PORT: number;
  ACCOUNT_PRI_KEY: string;
  /** 注意拼写就是 DEALDER_API_*，与代码里的引用保持一致。 */
  DEALDER_API_IP: string;
  DEALDER_API_PORT: number;
  VERSION: string;
  APP_WEB: string;
}

/** 大厅服配置（:9001 客户端、:9002 游戏服上报）。 */
export interface HallServerConfig {
  HALL_IP: string;
  /** 注意拼写就是 CLEINT_PORT（历史拼写错误），不要"顺手修正"。 */
  CLEINT_PORT: number;
  FOR_ROOM_IP: string;
  ROOM_PORT: number;
  ACCOUNT_PRI_KEY: string;
  ROOM_PRI_KEY: string;
}

/** 游戏服配置（:10000 Socket.IO、:9003 内部 HTTP）。 */
export interface GameServerConfig {
  SERVER_ID: string;
  HTTP_PORT: number;
  HTTP_TICK_TIME: number;
  HALL_IP: string;
  FOR_HALL_IP: string;
  HALL_PORT: number;
  ROOM_PRI_KEY: string;
  CLIENT_IP: string;
  CLIENT_PORT: number;
}

/** 一份配置文件的完整导出面。 */
export interface ServerConfigs {
  mysql(): MysqlConfig;
  account_server(): AccountServerConfig;
  hall_server(): HallServerConfig;
  game_server(): GameServerConfig;
}
