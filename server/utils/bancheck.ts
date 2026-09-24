/**
 * 封禁校验：游戏服 → 管理平台（`platform_server`）的内部只读接口。
 *
 * 大厅服与游戏服两个进程在**登录 / 进房前**问一句"这个玩家被封了吗"，
 * 问的对象是管理平台：
 *
 *     GET <PLATFORM>/api/internal/players/ban-check/?account=..&sign=..
 *     GET <PLATFORM>/api/internal/players/ban-check/?player_id=..&sign=..
 *     sign = md5("account" + account + "player_id" + player_id + PRI_KEY)
 *
 * 对应 `server-python/utils/bancheck.py`，两侧的**行为与签名必须逐字一致**
 * （参考向量钉在 `server-python/tests/test_protocol.py` 与 `tools/lib/smoke.mjs`）。
 *
 * 三条设计决定（改之前先读）
 * --------------------------
 *
 * 1. **fail-open**：超时、连不上、平台返回非 0，一律当作"没被封"放行，只打警告日志。
 *    理由：管理后台是运营工具，它挂掉不该让**全体玩家**登不上游戏。
 *    代价是平台故障期间被封玩家能临时进游戏——这是刻意的取舍，写进了 README/AGENTS。
 * 2. **缓存**：成功的结果按 `CACHE_TTL_MS` 缓存（正负都缓存），所以"后台点封禁"到
 *    "玩家被拦下"最多滞后一个 TTL；失败的调用不缓存结果本身，但会进入
 *    `FAIL_COOLDOWN_MS` 的冷却窗口，避免平台挂掉时**每次登录都白等一个超时**。
 * 3. **回调一定有且只有一次**：调用方（HTTP 处理器 / socket 处理器）拿到的必然是
 *    一个 `BanStatus`，不会因为平台抖动而把登录链路的回调吞掉或重复调用。
 *
 * **密钥不一致的表现是"封禁静默失效"**：平台回 10003、游戏服 fail-open 放行，
 * 只在日志里留一行警告。排查封禁不生效时，先看这行日志，再核对两侧密钥。
 *
 * 这里刻意**不用 `utils/http.ts` 的 `get()`**：那个共享出口没有超时参数，
 * 而登录链路必须有一个硬超时；给共享出口加超时会改变账号服/大厅服既有调用的行为。
 */

import * as nodeHttp from "node:http";
import { createHash } from "node:crypto";

import type { BanCheckConfig } from "../types/config";

/** 内部接口路径（与 `platform_server/apps/players/urls_internal.py` 对应）。 */
export const BAN_CHECK_PATH = "/api/internal/players/ban-check/";

/** 签名串里的字段标签。带上字段名，两个参数互相错位也不会撞出同一个签名。 */
const ACCOUNT_LABEL = "account";
const PLAYER_ID_LABEL = "player_id";

/** 失败后的冷却窗口（毫秒）：窗口内不再发请求，直接按"不知道"放行。 */
const FAIL_COOLDOWN_MS = 5000;

/** 缓存条目上限。超过就整体清空——刻意的粗粒度回收，理由见 Python 版同名常量。 */
const MAX_CACHE_ENTRIES = 5000;

/** 一次封禁校验的结果。 */
export interface BanStatus {
  /**
   * 是否真的问到了平台。
   *
   * `false` 表示"没问到"（未启用 / 冷却中 / 调用失败），此时 `banned` 恒为 false
   * （fail-open），调用方一律放行。
   */
  known: boolean;
  banned: boolean;
  reason: string;
  expiresAt: string | null;
  playerId: number | null;
}

/** 内部接口返回体的形状。 */
interface BanCheckBody {
  code?: number;
  message?: string;
  data?: unknown;
}

let config: BanCheckConfig | null = null;
const cache: Map<string, { expiresAtMs: number; status: BanStatus }> = new Map();
let cooldownUntil = 0;

/** 进程启动时注入配置（大厅服与游戏服的 app.ts 各自调用一次）。 */
export function init(loaded: BanCheckConfig): void {
  config = loaded;
}

/** 清掉配置与缓存（测试用；进程里没有调用点）。 */
export function reset(): void {
  config = null;
  cache.clear();
  cooldownUntil = 0;
}

function requireConfig(): BanCheckConfig {
  if (config === null) {
    throw new Error("utils/bancheck.init() 尚未调用");
  }
  return config;
}

/**
 * 算出内部接口的签名（与平台侧 `apps/players/internal.py` 同一公式）。
 *
 * @param account 玩家账号；不按账号查时传 `null`。
 * @param playerId 玩家 ID；不按 ID 查时传 `null`。
 * @param key 共享密钥（配置里的 `PRI_KEY`）。
 */
export function buildSign(
  account: string | null | undefined,
  playerId: number | null,
  key: string,
): string {
  const content =
    ACCOUNT_LABEL +
    (account ?? "") +
    PLAYER_ID_LABEL +
    (playerId === null ? "" : String(playerId)) +
    key;
  return createHash("md5").update(content, "utf8").digest("hex");
}

/** "没问到"的统一答案：放行。 */
function unknown(): BanStatus {
  return { known: false, banned: false, reason: "", expiresAt: null, playerId: null };
}

/**
 * 把封禁状态拼成给玩家看的一句话。
 *
 * 大厅服（HTTP）与游戏服（socket）共用它，保证同一个封禁在两条链路上文案一致；
 * 客户端拿到 `errmsg` 后原样提示。
 */
export function banMessage(status: BanStatus): string {
  const parts: string[] = ["账号已被封禁"];
  if (status.reason) {
    parts.push("原因：" + status.reason);
  }
  if (status.expiresAt) {
    parts.push("自动解封时间：" + status.expiresAt);
  } else {
    parts.push("永久封禁");
  }
  return parts.join("；") + "。如有疑问请联系客服。";
}

/** 按账号查封禁状态（大厅服走这条，它手里只有 account）。 */
export function checkAccount(
  account: string | null | undefined,
  callback: (status: BanStatus) => void,
): void {
  const text = (account ?? "").trim();
  if (!text) {
    callback(unknown());
    return;
  }
  check("account:" + text, { account: text }, text, null, callback);
}

/** 按玩家 ID 查封禁状态（游戏服从 token 里拿到的是 userId）。 */
export function checkUserId(userId: number, callback: (status: BanStatus) => void): void {
  if (!Number.isFinite(userId) || userId <= 0) {
    callback(unknown());
    return;
  }
  check("player_id:" + String(userId), { player_id: userId }, "", userId, callback);
}

/** 带缓存 / 冷却的查询。任何失败都回调 `unknown()`。 */
function check(
  cacheKey: string,
  params: Record<string, string | number>,
  account: string,
  playerId: number | null,
  callback: (status: BanStatus) => void,
): void {
  const loaded = requireConfig();
  if (!loaded.ENABLE) {
    callback(unknown());
    return;
  }

  const now = Date.now();
  const cached = cache.get(cacheKey);
  if (cached !== undefined && cached.expiresAtMs > now) {
    callback(cached.status);
    return;
  }
  if (now < cooldownUntil) {
    // 平台刚失败过：冷却期内不再打，避免每次登录都白等一个超时。
    callback(unknown());
    return;
  }

  const query: Record<string, string | number> = Object.assign({}, params);
  query.sign = buildSign(account, playerId, loaded.PRI_KEY);

  request(loaded, query, function (error: Error | null, status: BanStatus | null) {
    if (error !== null || status === null) {
      cooldownUntil = Date.now() + FAIL_COOLDOWN_MS;
      console.warn(
        "[bancheck] 封禁校验失败，本次放行（" +
          cacheKey +
          "）：" +
          (error === null ? "unknown" : error.message) +
          "。请检查平台地址与两侧密钥是否一致。",
      );
      callback(unknown());
      return;
    }
    store(cacheKey, status, loaded);
    callback(status);
  });
}

/** 写缓存（超上限时整体清空）。 */
function store(cacheKey: string, status: BanStatus, loaded: BanCheckConfig): void {
  if (cache.size >= MAX_CACHE_ENTRIES) {
    cache.clear();
  }
  cache.set(cacheKey, { expiresAtMs: Date.now() + loaded.CACHE_TTL_MS, status: status });
}

/** 真正发一次请求；失败时回调错误，由 `check` 负责 fail-open。 */
function request(
  loaded: BanCheckConfig,
  params: Record<string, string | number>,
  callback: (error: Error | null, status: BanStatus | null) => void,
): void {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    search.set(key, String(value));
  }

  let done = false;
  function finish(error: Error | null, status: BanStatus | null): void {
    // 超时与 error 事件可能都到；回调只允许发生一次。
    if (done) {
      return;
    }
    done = true;
    callback(error, status);
  }

  const req = nodeHttp.get(
    {
      hostname: loaded.HOST,
      port: loaded.PORT,
      path: BAN_CHECK_PATH + "?" + search.toString(),
      method: "GET",
      timeout: loaded.TIMEOUT_MS,
    },
    function (res) {
      let text = "";
      res.setEncoding("utf8");
      res.on("data", function (chunk: string) {
        text += chunk;
      });
      res.on("end", function () {
        try {
          finish(null, parseBody(text));
        } catch (error) {
          finish(error instanceof Error ? error : new Error(String(error)), null);
        }
      });
    },
  );

  // 连接/读取超时：node 只发 'timeout' 事件，必须自己销毁请求才会走 'error'。
  req.on("timeout", function () {
    req.destroy(new Error("timeout after " + String(loaded.TIMEOUT_MS) + "ms"));
  });
  req.on("error", function (error: Error) {
    finish(error, null);
  });
}

/** 解析平台返回体；不是成功外壳就抛错（由 `check` fail-open 兜住）。 */
function parseBody(text: string): BanStatus {
  const body: BanCheckBody = JSON.parse(text);
  if (body.code !== 0) {
    throw new Error("平台返回 code=" + String(body.code) + " message=" + String(body.message));
  }
  const data: unknown = body.data;
  if (data === null || typeof data !== "object") {
    throw new Error("平台返回的 data 不是对象");
  }
  const record = data as {
    known?: unknown;
    banned?: unknown;
    reason?: unknown;
    expires_at?: unknown;
    player_id?: unknown;
  };
  const expiresAt = record.expires_at;
  return {
    known: record.known !== false,
    banned: record.banned === true,
    reason: typeof record.reason === "string" ? record.reason : "",
    expiresAt: typeof expiresAt === "string" && expiresAt !== "" ? expiresAt : null,
    playerId: typeof record.player_id === "number" ? record.player_id : null,
  };
}
