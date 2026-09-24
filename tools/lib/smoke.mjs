/**
 * Behavioural smoke tests for pure server logic.
 *
 * The gate must stay dependency-free and offline, and the full server needs a
 * live MySQL instance (the old `fibers` boot blocker is gone; see server/AGENTS.md
 * §1.1). That would normally mean zero behavioural coverage in CI.
 *
 * These cases deliberately load only modules that touch neither: the mahjong
 * rules engine (`mjutils`) is pure arithmetic over a seat's tile counts, and the
 * crypto helper wraps Node's built-in `crypto`. They pin the two most
 * consequential pure contracts in the repository, so a refactor that silently
 * changes win detection or signature generation fails the gate instead of the
 * players.
 */

import { createRequire } from "node:module";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import Module from "node:module";
import * as nodeModule from "node:module";

const require = createRequire(import.meta.url);

/** `module.stripTypeScriptTypes` exists on Node >= 22.13; the gate must survive older Node. */
const stripTypeScriptTypes =
  typeof nodeModule.stripTypeScriptTypes === "function" ? nodeModule.stripTypeScriptTypes : null;

/**
 * Load one first-party server module for behaviour testing, without requiring a
 * build step or an `npm install`.
 *
 * Order of attempts:
 *   1. `require("<name>.ts")` — native TypeScript execution (Node >= 22.18);
 *   2. strip the types with the Node built-in and compile the result as CommonJS
 *      (Node >= 22.13; only helps for CommonJS-style sources);
 *   3. `<name>.js` next to the source, then `server/dist/<name>.js` — the build
 *      output, for a Node too old for either of the above.
 *
 * Every failure is collected and reported: a module that cannot be loaded is a
 * failed smoke check, never a silently smaller test run.
 *
 * @param {string} root repository root.
 * @param {string} relativeBase module path without extension, e.g. `game_server/mjutils`.
 * @returns {{ module?: object, error?: string }} the loaded module or why it could not load.
 */
function loadServerModule(root, relativeBase) {
  const attempts = [];
  const tsPath = join(root, "server", `${relativeBase}.ts`);
  const candidates = [tsPath, join(root, "server", `${relativeBase}.js`), join(root, "server/dist", `${relativeBase}.js`)];

  if (existsSync(tsPath)) {
    try {
      return { module: require(tsPath) };
    } catch (error) {
      attempts.push(`${tsPath}: ${describe(error)}`);
    }
    if (stripTypeScriptTypes !== null) {
      try {
        const compiled = stripTypeScriptTypes(readFileSync(tsPath, "utf8"), { mode: "strip" });
        const loaded = new Module(tsPath, null);
        loaded.filename = tsPath;
        loaded.paths = Module._nodeModulePaths(dirname(tsPath));
        loaded._compile(compiled, tsPath);
        return { module: loaded.exports };
      } catch (error) {
        attempts.push(`${tsPath} (strip+compile): ${describe(error)}`);
      }
    }
  }

  for (const candidate of candidates.slice(1)) {
    if (!existsSync(candidate)) continue;
    try {
      return { module: require(candidate) };
    } catch (error) {
      attempts.push(`${candidate}: ${describe(error)}`);
    }
  }

  return { error: attempts.join(" | ") || `找不到 ${relativeBase}.ts（也没有 .js 或 dist 产物）` };
}

/** @param {unknown} error @returns {string} */
function describe(error) {
  return error instanceof Error ? error.message : String(error);
}

/** @type {{ name: string, ok: boolean, detail?: string }[]} */
const results = [];

/**
 * Record one assertion.
 * @param {string} name assertion label.
 * @param {boolean} condition assertion outcome.
 * @param {string} [detail] explanation shown on failure.
 */
function assert(name, condition, detail) {
  results.push({ name, ok: condition === true, ...(detail === undefined ? {} : { detail }) });
}

/**
 * Build the seat shape `checkTingPai` expects from a tile list.
 *
 * Tile ids follow the engine's convention: 0-8 筒 (dots), 9-17 条 (bamboo),
 * 18-26 万 (characters).
 *
 * @param {number[]} holds tile ids in hand.
 * @returns {{ holds: number[], countMap: Record<number, number>, tingMap: Record<number, unknown> }}
 */
export function buildSeat(holds) {
  const countMap = {};
  for (const tile of holds) countMap[tile] = (countMap[tile] ?? 0) + 1;
  return { holds: [...holds], countMap, tingMap: {} };
}

/**
 * Run every smoke case.
 * @param {string} root repository root.
 * @returns {Promise<{ ok: boolean, checks: { name: string, ok: boolean, detail?: string }[], error?: string }>}
 */
export async function runSmoke(root) {
  const mjutilsLoad = loadServerModule(root, "game_server/mjutils");
  const cryptoLoad = loadServerModule(root, "utils/crypto");
  const httpLoad = loadServerModule(root, "utils/http");
  const bancheckLoad = loadServerModule(root, "utils/bancheck");
  if (
    mjutilsLoad.error !== undefined ||
    cryptoLoad.error !== undefined ||
    httpLoad.error !== undefined ||
    bancheckLoad.error !== undefined
  ) {
    return {
      ok: false,
      checks: [],
      error: `could not load pure server modules: ${[mjutilsLoad.error, cryptoLoad.error, httpLoad.error, bancheckLoad.error].filter(Boolean).join(" | ")}`,
    };
  }

  const mjutils = mjutilsLoad.module;
  const crypto = cryptoLoad.module;
  const http = httpLoad.module;
  const bancheck = bancheckLoad.module;

  // Callers always pass a complete 13-tile hand, so the waits are exactly the
  // 14th tiles that would complete it.

  // 1. Four melds already formed; the single 5条 (13) must pair up.
  const pairWait = buildSeat([18, 19, 20, 21, 22, 23, 24, 25, 26, 9, 9, 9, 13]);
  mjutils.checkTingPai(pairWait, 0, 27);
  assert(
    "checkTingPai detects a pair wait",
    Object.keys(pairWait.tingMap).join(",") === "13",
    `expected only tile 13, got ${JSON.stringify(pairWait.tingMap)}`,
  );

  // 2. Four pungs plus a lone 5条: the same wait found by a different route.
  const pungWait = buildSeat([18, 18, 18, 19, 19, 19, 20, 20, 20, 21, 21, 21, 13]);
  mjutils.checkTingPai(pungWait, 0, 27);
  assert(
    "checkTingPai detects a wait behind four pungs",
    Object.keys(pungWait.tingMap).join(",") === "13",
    `expected only tile 13, got ${JSON.stringify(pungWait.tingMap)}`,
  );

  // 3. Two runs of the same run plus a spare pair member: 18-19-20 twice and
  //    21-22-23 twice is four sequences, and 24 pairs up as the eyes. This is an
  //    ordinary 3N win reached by a non-obvious decomposition, so it guards the
  //    sequence-matching backtracking. NB: this hand *looks* like it could be
  //    read as pairs, but the engine has no seven-pairs rule (see case 5).
  const twoRuns = buildSeat([18, 18, 19, 19, 20, 20, 21, 21, 22, 22, 23, 23, 24]);
  mjutils.checkTingPai(twoRuns, 0, 27);
  assert(
    "checkTingPai decomposes two identical runs plus a pair",
    Object.keys(twoRuns.tingMap).join(",") === "18,21,24",
    `expected 18,21,24, got ${JSON.stringify(twoRuns.tingMap)}`,
  );

  // 4. A hand that is nowhere near a win must report no waits at all, so a
  //    regression cannot pass by lighting up every tile.
  const nowhere = buildSeat([0, 3, 6, 9, 12, 15, 18, 21, 24, 1, 5, 10, 14]);
  mjutils.checkTingPai(nowhere, 0, 27);
  assert(
    "checkTingPai reports no waits for a disconnected hand",
    Object.keys(nowhere.tingMap).length === 0,
    `expected no waits, got ${JSON.stringify(nowhere.tingMap)}`,
  );

  // 5. Pinned limitation: seven pairs is NOT a win in this engine. Six pairs plus
  //    a lone 1万 is one tile from seven pairs but the engine reports no wait,
  //    because checkCanHu only enumerates a pair and then validates triplets and
  //    sequences. This assertion documents current behaviour so that adding the
  //    rule is a deliberate, visible change rather than a silent regression.
  const sixPairs = buildSeat([0, 0, 3, 3, 6, 6, 9, 9, 12, 12, 15, 15, 18]);
  mjutils.checkTingPai(sixPairs, 0, 27);
  assert(
    "checkTingPai does not implement seven pairs (documented limitation)",
    Object.keys(sixPairs.tingMap).length === 0,
    `seven pairs unexpectedly detected: ${JSON.stringify(sixPairs.tingMap)}`,
  );

  // 3. Tile classification boundaries: 筒 0-8, 条 9-17, 万 18-26.
  assert("getMJType maps 筒", mjutils.getMJType(0) === 0 && mjutils.getMJType(8) === 0);
  assert("getMJType maps 条", mjutils.getMJType(9) === 1 && mjutils.getMJType(17) === 1);
  assert("getMJType maps 万", mjutils.getMJType(18) === 2 && mjutils.getMJType(26) === 2);

  // 4. Room-login signatures are md5(roomId + token + time + ROOM_PRI_KEY); the
  //    server and the dealer both compute them with this helper.
  assert(
    "crypto.md5 matches the reference digest",
    crypto.md5("hello") === "5d41402abc4b2a76b9719d911017c592",
    `got ${crypto.md5("hello")}`,
  );

  // 5. Base64 round-trip: player names go into MySQL base64-encoded and come back
  //    through this pair, so non-ASCII names must survive intact.
  assert(
    "crypto base64 round-trips ASCII",
    crypto.fromBase64(crypto.toBase64("babykylin")) === "babykylin",
  );
  assert(
    "crypto base64 round-trips non-ASCII player names",
    crypto.fromBase64(crypto.toBase64("四川麻将玩家")) === "四川麻将玩家",
    `got ${crypto.fromBase64(crypto.toBase64("四川麻将玩家"))}`,
  );

  // 6. `String.prototype.format` is infrastructure, not a detail: the SQL layer in
  //    `utils/db.ts` builds 11 statements with it. The patch lives at the top of
  //    `utils/http.ts`, so this pins both its existence and its two call shapes.
  assert(
    "String.prototype.format replaces positional placeholders",
    "a={0},b={1}".format("x", 2) === "a=x,b=2",
    `got ${"a={0},b={1}".format("x", 2)}`,
  );
  assert(
    "String.prototype.format replaces named placeholders",
    "{x}-{y}".format({ x: "1", y: "2" }) === "1-2",
    `got ${"{x}-{y}".format({ x: "1", y: "2" })}`,
  );
  assert(
    "String.prototype.format leaves placeholders alone with no arguments",
    "{0}".format() === "{0}",
    `got ${"{0}".format()}`,
  );

  // 7. Query helpers. express widens every query value to
  //    `string | string[] | ParsedQs | ParsedQs[] | undefined`; these two narrow it
  //    back for the whole server, so their contract is worth pinning. A repeated
  //    parameter is deliberately treated as "not provided" (see the doc comment).
  const fakeRequest = { query: { s: "abc", n: "42", dup: ["a", "b"] } };
  assert("queryString returns a plain string parameter", http.queryString(fakeRequest, "s") === "abc");
  assert(
    "queryString refuses repeated parameters",
    http.queryString(fakeRequest, "dup") === undefined,
    `got ${JSON.stringify(http.queryString(fakeRequest, "dup"))}`,
  );
  assert("queryString returns undefined when absent", http.queryString(fakeRequest, "nope") === undefined);
  assert("queryInt parses an integer parameter", http.queryInt(fakeRequest, "n") === 42);
  assert(
    "queryInt is NaN when the parameter is absent (matches parseInt)",
    Number.isNaN(http.queryInt(fakeRequest, "nope")),
    `got ${http.queryInt(fakeRequest, "nope")}`,
  );

  // 8. 封禁校验的签名。这是**游戏服与平台之间唯一的运行时契约**：签名串由 Node、
  //    Python、platform_server 三处各写一遍，只有一个字面量向量能钉住它们一致。
  //    向量与 server-python/tests/test_protocol.py、platform_server/tests/test_players.py
  //    里的常量相同（密钥取 configs 的开发默认值）。
  const banKey = "scmj-ban-check-dev-key";
  assert(
    "bancheck sign (by account) matches the cross-implementation vector",
    bancheck.buildSign("guest_123456", null, banKey) === "72977b2a422916d846f1f8b9bb10528d",
    `got ${bancheck.buildSign("guest_123456", null, banKey)}`,
  );
  assert(
    "bancheck sign (by player_id) matches the cross-implementation vector",
    bancheck.buildSign(null, 9, banKey) === "e16efd54aaddb8fb2aada5912ca306cd",
    `got ${bancheck.buildSign(null, 9, banKey)}`,
  );
  assert(
    "bancheck sign (both fields) matches the cross-implementation vector",
    bancheck.buildSign("guest_123456", 9, banKey) === "d4cb51c910c644dc4b29a94a62dded4b",
    `got ${bancheck.buildSign("guest_123456", 9, banKey)}`,
  );
  assert(
    "bancheck field labels keep the two parameters from aliasing",
    bancheck.buildSign("9", null, banKey) !== bancheck.buildSign(null, 9, banKey),
  );
  assert(
    "bancheck endpoint path matches platform_server's route",
    bancheck.BAN_CHECK_PATH === "/api/internal/players/ban-check/",
    `got ${bancheck.BAN_CHECK_PATH}`,
  );
  //    fail-open 的真实路径：未启用时**不发任何请求**，直接回调"不知道 = 放行"。
  bancheck.init({
    ENABLE: false,
    HOST: "127.0.0.1",
    PORT: 1,
    PRI_KEY: banKey,
    TIMEOUT_MS: 10,
    CACHE_TTL_MS: 10,
  });
  const disabledStatus = await new Promise((resolve) => bancheck.checkAccount("guest_1", resolve));
  bancheck.reset();
  assert(
    "bancheck is fail-open: disabled config answers unknown (allow, no request)",
    disabledStatus.known === false && disabledStatus.banned === false,
    `got ${JSON.stringify(disabledStatus)}`,
  );
  assert(
    "bancheck message tells the player the reason and the expiry",
    bancheck.banMessage({
      known: true,
      banned: true,
      reason: "使用外挂",
      expiresAt: "2026-01-01 00:00:00",
      playerId: 9,
    }) === "账号已被封禁；原因：使用外挂；自动解封时间：2026-01-01 00:00:00。如有疑问请联系客服。",
    bancheck.banMessage({
      known: true,
      banned: true,
      reason: "使用外挂",
      expiresAt: "2026-01-01 00:00:00",
      playerId: 9,
    }),
  );

  return { ok: results.every((entry) => entry.ok), checks: results };
}
