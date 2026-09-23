/**
 * Behavioural smoke tests for pure server logic.
 *
 * The full server cannot boot in a modern Node runtime: `server/utils/http.js`
 * and the account server `require('fibers')`, a native addon that has no binary
 * for current Node versions, and the data layer needs a live MySQL instance.
 * That would normally mean zero behavioural coverage.
 *
 * These cases deliberately load only modules that touch neither: the mahjong
 * rules engine (`mjutils`) is pure arithmetic over a seat's tile counts, and the
 * crypto helper wraps Node's built-in `crypto`. They pin the two most
 * consequential pure contracts in the repository, so a refactor that silently
 * changes win detection or signature generation fails the gate instead of the
 * players.
 */

import { createRequire } from "node:module";
import { join } from "node:path";

const require = createRequire(import.meta.url);

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
  let mjutils;
  let crypto;
  try {
    mjutils = require(join(root, "server/game_server/mjutils.js"));
    crypto = require(join(root, "server/utils/crypto.js"));
  } catch (error) {
    return {
      ok: false,
      checks: [],
      error: `could not load pure server modules: ${error instanceof Error ? error.message : String(error)}`,
    };
  }

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

  return { ok: results.every((entry) => entry.ok), checks: results };
}
