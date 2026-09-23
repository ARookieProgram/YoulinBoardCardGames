/**
 * 客户端宿主环境的全局补丁声明。
 *
 * 这些类型只服务于 `tsc --noEmit` 与编辑器补全：`.d.ts` 不产生运行时代码，
 * 也不参与 Creator 的脚本编译，所以这里怎么声明都不会改变游戏行为。
 *
 * 声明的是 `creator.d.ts` 没有覆盖、却由 Creator 运行时或宿主页面提供的全局量：
 * 脚本模块加载器 `require`、vendored socket.io 暴露的 `window.io` 等。
 */

/** Creator 的脚本模块加载器：按资源名加载 `assets/scripts` 下的模块，如 `require("HTTP")`。 */
declare function require(moduleName: string): unknown;

/** vendored socket.io 客户端（`assets/scripts/3rdparty/socket-io.js`）挂在 `window.io` 上。 */
interface Window {
    io: SocketIOClient;
}

/** socket.io 1.x 客户端的最小类型声明，只覆盖本项目实际用到的 API。 */
interface SocketIOClient {
    connect(ip: string, options: SocketIOConnectOptions): SocketIOSocket;
}

/** `io.connect` 的选项：项目里只传这三个字段。 */
interface SocketIOConnectOptions {
    reconnection: boolean;
    "force new connection": boolean;
    transports: string[];
}

/** 一条 socket.io 连接。事件回调收到的原始数据统一按 unknown 处理，由调用方收窄。 */
interface SocketIOSocket {
    connected: boolean;
    on(event: string, handler: (data: unknown) => void): void;
    emit(event: string, data?: string): void;
    disconnect(): void;
}
