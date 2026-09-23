/**
 * Socket.IO 协议的类型视图。
 *
 * 这里给的是**事件名与方向**，以及连接对象上本仓库自己挂的字段。
 * 事件清单以 `repo:docs/ai-native/protocol.md` 为准，并由 `npm run check:protocol` 双向校验
 * （服务端推送 vs 客户端 `addHandler`）——那份检查基于源码字符串，不依赖这里的类型，
 * 所以两边都要维护：新增事件时，改代码、改 protocol.md、改本文件。
 *
 * 载荷刻意保持宽：跨进程协议的真实结构由 protocol.md 的表格与客户端代码约束，
 * TypeScript 无法静态校验。这里只保证"不是 any"。
 */

import type { GameManager } from "./domain";
import type { RawSocket } from "socket.io";

/**
 * 可推送给客户端的载荷。
 *
 * 用 `object` 而不是 `Record<string, unknown>`：后者会拒绝**具名接口**（TS 对 interface
 * 不提供隐式索引签名），逼着所有载荷都写成 type 别名，反而更脆。
 */
export type SocketPayload = object | string | number | boolean | null | undefined;

/** 服务端 → 客户端的事件名（protocol.md §1 的 39 个）。 */
export type ServerPushEvent =
  | "chat_push"
  | "dispress_push"
  | "dissolve_cancel_push"
  | "dissolve_notice_push"
  | "emoji_push"
  | "exit_notify_push"
  | "exit_result"
  | "game_action_push"
  | "game_begin_push"
  | "game_chupai_notify_push"
  | "game_chupai_push"
  | "game_dingque_finish_push"
  | "game_dingque_notify_push"
  | "game_dingque_push"
  | "game_holds_push"
  | "game_huanpai_over_push"
  | "game_huanpai_push"
  | "game_mopai_push"
  | "game_num_push"
  | "game_over_push"
  | "game_playing_push"
  | "game_pong"
  | "game_sync_push"
  | "gang_notify_push"
  | "guo_notify_push"
  | "guo_result"
  | "guohu_push"
  | "hangang_notify_push"
  | "hu_push"
  | "huanpai_notify"
  | "login_finished"
  | "login_result"
  | "mj_count_push"
  | "new_user_comes_push"
  | "peng_notify_push"
  | "quick_chat_push"
  | "user_ready_push"
  | "user_state_push"
  | "voice_msg_push";

/** 换三张的入参（`huanpai` 事件里除了 JSON 字符串之外的另一种形态）。 */
export interface HuanPaiPayload {
  p1: number;
  p2: number;
  p3: number;
}

/**
 * 客户端 → 服务端的事件处理器签名（protocol.md §2）。
 *
 * 未使用的载荷统一写 `unknown`：socket_service 里这些处理器本来就不读参数，
 * 留 `unknown` 比编一个假结构更诚实。
 */
export interface ClientToServerEvents {
  /** 进房握手：socket.io 传过来的是 JSON 字符串，服务端自己 JSON.parse。 */
  login(data: string): void;
  ready(data: unknown): void;
  /** 换三张：可能是 JSON 字符串，也可能是已经解析好的对象。 */
  huanpai(data: string | HuanPaiPayload): void;
  /** 定缺花色：0 筒 / 1 条 / 2 万。 */
  dingque(data: number): void;
  /** 出牌：牌 id 0-26。 */
  chupai(data: number): void;
  peng(data: unknown): void;
  /** 杠：可能是数字，也可能是数字字符串。 */
  gang(data: number | string): void;
  hu(data: unknown): void;
  guo(data: unknown): void;
  chat(data: string): void;
  quick_chat(data: number): void;
  voice_msg(data: string): void;
  emoji(data: number): void;
  exit(data: unknown): void;
  dispress(data: unknown): void;
  dissolve_request(data: unknown): void;
  dissolve_agree(data: unknown): void;
  dissolve_reject(data: unknown): void;
  game_ping(data: unknown): void;
}

/**
 * 对局连接对象：socket.io 的连接 + 本仓库挂在上面的字段。
 *
 * `socket.io` 本身没有类型，`RawSocket` 是 `types/socket.io.d.ts` 里的最小声明；
 * 在 `socket_service.ts` 的连接回调处做唯一一次断言，之后所有业务代码都用这个类型。
 */
export interface GameSocket extends Omit<RawSocket, "emit" | "on"> {
  /** 登录成功后写入；未登录为 null。 */
  userId: number | null;
  /** 登录成功后写入，指向房间所用的玩法实现。 */
  gameMgr: GameManager;
  emit(event: ServerPushEvent, payload?: SocketPayload): boolean;
  on<E extends keyof ClientToServerEvents>(event: E, listener: ClientToServerEvents[E]): this;
  /** socket.io 内置的断开事件，载荷是断开原因。 */
  on(event: "disconnect", listener: (reason: string) => void): this;
}
