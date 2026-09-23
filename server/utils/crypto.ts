import * as nodeCrypto from "node:crypto";

/**
 * 摘要与 Base64 工具。
 *
 * 用途：
 * - `md5`：进房签名（`md5(roomid + token + time + ROOM_PRI_KEY)`）、大厅服与游戏服之间的
 *   内部接口签名，以及 token 生成；
 * - `toBase64` / `fromBase64`：用户名进出库的编码（`utils/db.ts` 内部使用）。
 *
 * 行为与迁移前逐字一致，`npm run check:smoke` 会用已知向量钉住 md5 与 Base64 往返。
 */

/**
 * 计算字符串的 md5（小写十六进制）。
 * @param content 待摘要内容。
 * @returns 32 位十六进制摘要。
 */
export function md5(content: string): string {
  const hash = nodeCrypto.createHash("md5");
  hash.update(content);
  return hash.digest("hex");
}

/**
 * UTF-8 字符串转 Base64。
 * @param content 原文。
 * @returns Base64 文本。
 */
export function toBase64(content: string): string {
  // 使用 Buffer.from；new Buffer() 在当前 Node 上会打印弃用告警
  return Buffer.from(content, "utf8").toString("base64");
}

/**
 * Base64 还原 UTF-8 字符串。
 * @param content Base64 文本。
 * @returns 原文。
 */
export function fromBase64(content: string): string {
  return Buffer.from(content, "base64").toString("utf8");
}
