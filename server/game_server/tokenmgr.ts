import * as crypto from "../utils/crypto";

/**
 * 房间登录 token 的生成与有效期校验。
 *
 * token 由游戏服的 `/enter_room` 内部接口创建（`http_service.ts`），客户端带着它去
 * `socket.io` 登录；`socket_service.ts` 用它换 userId。
 */

/** 一条 token 记录。 */
interface TokenInfo {
  userId: number;
  /** 生成时刻（毫秒）。 */
  time: number;
  /** 有效期，由 createToken 的入参写入。 */
  lifeTime: number;
}

/** token -> 记录；delToken 会把它置成 null（原实现如此，不是 delete）。 */
var tokens: Record<string, TokenInfo | null> = {};
/** userId -> token。 */
var users: Record<number, string | null> = {};

/**
 * `createToken` 里的 `this`。
 *
 * 原实现写的是 `this.delToken(token)`，调用方都是 `tokenMgr.createToken(...)`，
 * 此时 `this` 就是本模块。用 `this` 参数把这个前提写进类型，而不是改成直接调用
 * （直接调用会悄悄改变"以别的形式引用该函数"时的行为）。
 */
interface TokenMgrThis {
  delToken(token: string): void;
}

/**
 * 为一个玩家签发 token（同一玩家已有 token 时先作废旧的）。
 *
 * @param userId 玩家 id。
 * @param lifeTime 有效期（毫秒）。
 * @returns 新 token。
 */
export function createToken(this: TokenMgrThis, userId: number, lifeTime: number): string {
	var token = users[userId];
	if(token != null){
		this.delToken(token);
	}

	var time = Date.now();
	token = crypto.md5(userId + "!@#$%^&" + time);
	tokens[token] = {
		userId: userId,
		time: time,
		lifeTime: lifeTime
	};
	users[userId] = token;
	return token;
}

/**
 * 取某个玩家当前的 token。
 *
 * @param userId 玩家 id。
 * @returns token；没有则 undefined。
 */
export function getToken(userId: number): string | null | undefined {
	return users[userId];
}

/**
 * 用 token 换 userId。
 *
 * **行为保留**：原实现是 `tokens[token].userId`，token 不存在时会抛 TypeError。
 * 这里用非空断言保留同样的崩溃语义，而不是悄悄返回 undefined。
 *
 * @param token 进房 token。
 * @returns 该 token 对应的玩家 id。
 */
export function getUserID(token: string): number {
	return tokens[token]!.userId;
}

/**
 * token 是否有效。
 *
 * **历史 bug（迁移不修，改它要单独开一次改动）**：下面读的是 `info.lifetime`（小写 t），
 * 而 createToken 写入的字段是 `lifeTime`，因此取到 undefined，`time + undefined` 是 NaN，
 * `NaN < Date.now()` 恒为 false —— 本函数**恒返回 true**，token 实际上不过期。
 * `legacyLifetime` 把这一步单独写出来，是为了让这个行为在类型层面也说得通，
 * 而不是靠 `any` 蒙混过去。
 *
 * @param token 进房 token。
 * @returns 记录不存在时 false，存在时按上面的说明恒为 true。
 */
export function isTokenValid(token: string): boolean {
	var info = tokens[token];
	if(info == null){
		return false;
	}
	if(info.time + legacyLifetime(info) < Date.now()){
		return false;
	}
	return true;
}

/**
 * 删除 token（同时清掉玩家的 token 映射）。
 *
 * @param token 要删除的 token。
 */
export function delToken(token: string): void {
	var info = tokens[token];
	if(info != null){
		tokens[token] = null;
		users[info.userId] = null;
	}
}

/**
 * 读老代码里的 `info.lifetime`（小写 t）。这个字段从未被写入过，所以永远是 undefined。
 *
 * @param info token 记录。
 * @returns 恒为 NaN（对应原实现里 `time + undefined` 的结果）。
 */
function legacyLifetime(info: TokenInfo): number {
	return (info as { lifetime?: number }).lifetime ?? NaN;
}
