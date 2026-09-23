/**
 * `socket.io` 1.7 的最小类型声明。
 *
 * socket.io 1.x 不随包发布类型，DefinitelyTyped 上的 `@types/socket.io` 描述的是 2.x/3.x，
 * 与本仓库实际使用的 1.7.4 在 `Server`/`Namespace` 的形态上并不一致。与其引入一份
 * 版本不匹配的第三方类型，这里只声明本仓库**真正用到**的那几个成员，并保持每一条都能
 * 在 `socket.io/lib/*.js` 里找到对应实现。
 *
 * 事件词汇表不在这里：业务侧用的是 `types/protocol.ts` 里的 `GameSocket`（带事件名与
 * 载荷类型），两者在 `game_server/socket_service.ts` 的连接回调处一次性对接。
 */

declare module "socket.io" {
  import type { Server as HttpServer } from "node:http";

  /** 连接对象中本仓库用到的部分（socket.io 1.x `lib/socket.js`）。 */
  export interface RawSocket {
    /** 握手信息，登录时取 `handshake.address` 作为座位 ip。 */
    handshake: { address: string };
    emit(event: string, ...args: unknown[]): boolean;
    on(event: string, listener: (...args: unknown[]) => void): RawSocket;
    disconnect(close?: boolean): RawSocket;
  }

  /** 默认命名空间（socket.io 1.x `lib/namespace.js`）。 */
  export interface RawNamespace {
    on(event: "connection", listener: (socket: RawSocket) => void): void;
  }

  export interface RawServer {
    sockets: RawNamespace;
  }

  /** `require("socket.io")(httpServer)` 的形态。 */
  function socketio(server: HttpServer, options?: object): RawServer;
  export = socketio;
}
