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

/**
 * 封禁校验配置（游戏服 → 管理平台 `platform_server` 的内部只读接口）。
 *
 * 大厅服与游戏服两个进程都用它：登录 / 进房前问一句"这个玩家被封了吗"。
 * 契约见 `utils/bancheck.ts`（Node）与 `server-python/utils/bancheck.py`（Python），
 * 两侧的字段名与行为必须一致。
 *
 * `PRI_KEY` 必须与 `platform_server` 的 `PLATFORM_INTERNAL_KEY` 逐字相同：
 * 不一致的表现不是报错，而是游戏服侧 fail-open、**封禁静默失效**（只在日志里告警）。
 */
export interface BanCheckConfig {
  /** 是否启用校验。平台没部署时可以关掉，连 HTTP 请求都不发。 */
  ENABLE: boolean;
  /** 管理平台的地址与端口（默认本机 8000）。 */
  HOST: string;
  PORT: number;
  /** 与 platform_server 的 PLATFORM_INTERNAL_KEY 一致的共享密钥。 */
  PRI_KEY: string;
  /** 单次校验的超时（毫秒）。超时即 fail-open 放行。 */
  TIMEOUT_MS: number;
  /** 校验结果缓存时长（毫秒）。封禁生效 / 解除最多滞后这么久。 */
  CACHE_TTL_MS: number;
}

/** 一份配置文件的完整导出面。 */
export interface ServerConfigs {
  mysql(): MysqlConfig;
  account_server(): AccountServerConfig;
  hall_server(): HallServerConfig;
  game_server(): GameServerConfig;
  ban_check(): BanCheckConfig;
}
