/**
 * Self-test for the verification tooling.
 *
 * The checks in this directory are what every later change is judged against, so
 * a broken checker is worse than no checker: it would report success without
 * looking. These cases exercise the parsers and diffs against fixtures with known
 * answers, including the malformed inputs they are meant to reject.
 *
 * Run with: node --test tools/selftest.test.mjs
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { parseFrontmatter, extractRepoPaths } from "./lib/harness.mjs";
import {
  extractServerEvents,
  extractClientHandlers,
  extractDocumentedEvents,
  section,
  diffProtocol,
} from "./lib/protocol.mjs";
import { collectScripts, checkScriptSyntax } from "./lib/syntax.mjs";
import { buildSeat } from "./lib/smoke.mjs";

test("parseFrontmatter reads the flat key/value subset", () => {
  const { stated, fields, body, problems } = parseFrontmatter(
    ["---", "name: demo-skill", "description: Explains the demo domain.", "---", "", "Body text."].join("\n"),
  );
  assert.equal(stated, true);
  assert.deepEqual(problems, []);
  assert.equal(fields.name, "demo-skill");
  assert.equal(fields.description, "Explains the demo domain.");
  assert.equal(body.trim(), "Body text.");
});

test("parseFrontmatter strips quotes and joins block scalars", () => {
  const { fields } = parseFrontmatter(
    ["---", 'name: "quoted-name"', "description: >", "  first line", "  second line", "---", "body"].join("\n"),
  );
  assert.equal(fields.name, "quoted-name");
  assert.equal(fields.description, "first line second line");
});

test("parseFrontmatter rejects a document with no frontmatter", () => {
  const { stated, problems } = parseFrontmatter("# Just a heading\n");
  assert.equal(stated, false);
  assert.match(problems.join(" "), /missing '---' frontmatter block/);
});

test("parseFrontmatter reports an unterminated block", () => {
  const { stated, problems } = parseFrontmatter("---\nname: demo\n");
  assert.equal(stated, true);
  assert.match(problems.join(" "), /unterminated frontmatter block/);
});

test("parseFrontmatter flags nested structures instead of misreading them", () => {
  const { problems } = parseFrontmatter(["---", "name: demo", "metadata:", "  nested: true", "---", "body"].join("\n"));
  assert.match(problems.join(" "), /unsupported frontmatter line/);
});

test("extractRepoPaths keeps only repo:-prefixed spans", () => {
  const body = "See `repo:server/utils/db.js` and `not/a/path` plus `repo:client/project.json`.";
  assert.deepEqual(extractRepoPaths(body), ["client/project.json", "server/utils/db.js"]);
});

test("extractServerEvents finds both broadcast helpers and accepts both quote styles", () => {
  const source = [
    "userMgr.broacastInRoom('game_begin_push',data,sender,true);",
    'userMgr.sendMsg(seatData.userId,"guo_result");',
    "socket.emit('login_result',ret);",
    "userMgr.broacastInRoom('game_begin_push', other, sender, true);",
  ].join("\n");
  assert.deepEqual([...extractServerEvents(source)].sort(), ["game_begin_push", "guo_result", "login_result"]);
});

test("extractClientHandlers reads both registration paths", () => {
  const source = [
    'cc.vv.net.addHandler("login_result",function(data){});',
    "cc.vv.net.addHandler('hu_push',fn);",
    "this.sio.on('game_pong',function(){});",
    "this.sio.on('connect',function(){});",
  ].join("\n");
  assert.deepEqual([...extractClientHandlers(source)].sort(), ["connect", "game_pong", "hu_push", "login_result"]);
});

test("diffProtocol reports drift in both directions and ignores local events", () => {
  const server = new Set(["game_begin_push", "hu_push"]);
  const client = new Set(["game_begin_push", "disconnect", "game_over_push"]);
  const { unhandled, unsent } = diffProtocol(server, client);
  assert.deepEqual(unhandled, ["hu_push"]);
  assert.deepEqual(unsent, ["game_over_push"]);
});

test("diffProtocol tolerates the known dead client handler", () => {
  const { unhandled, unsent } = diffProtocol(new Set(["hu_push"]), new Set(["hu_push", "push_need_create_role"]));
  assert.deepEqual([unhandled, unsent], [[], []]);
});

test("section isolates one heading and stops at the next", () => {
  const markdown = ["# t", "## 1. 服务端推送事件（2 个）", "| `a_push` | x |", "## 2. 其他", "| `b` | y |"].join("\n");
  const body = section(markdown, "1. 服务端推送事件");
  assert.ok(body.includes("`a_push`"));
  assert.equal(body.includes("`b`"), false, "must stop at the next heading");
});

test("section matches a heading whose count changed, and misses cleanly", () => {
  // The count in the heading must not be part of the match, otherwise adding an
  // event would silently disable the documentation check.
  assert.ok(section("## 1. 服务端推送事件（999 个）\n| `x` |", "1. 服务端推送事件").includes("`x`"));
  assert.equal(section("# nothing here", "1. 服务端推送事件"), "");
});

test("extractDocumentedEvents reads only the push table, not other tables", () => {
  const markdown = [
    "## 1. 服务端推送事件（2 个）",
    "| 事件 | 作用域 | 服务端发出方式 |",
    "| --- | --- | --- |",
    "| `login_result` | 单人 | `socket.emit` |",
    "| `hu_push` | 房间广播 | `broacastInRoom` |",
    "## 2. 客户端 → 服务端",
    "| `login` | — | 进房握手 |",
    "| `dingque` | 花色 | 定缺 |",
  ].join("\n");
  const documented = extractDocumentedEvents(markdown);
  assert.deepEqual([...documented].sort(), ["hu_push", "login_result"]);
  assert.equal(documented.has("dingque"), false, "the client→server table must not be read");
});

test("diffProtocol is clean when both sides agree", () => {
  const server = new Set(["hu_push"]);
  const client = new Set(["hu_push", "connect_failed"]);
  const { unhandled, unsent } = diffProtocol(server, client);
  assert.deepEqual([unhandled, unsent], [[], []]);
});

test("checkScriptSyntax accepts valid JS and rejects a syntax error", async () => {
  const { mkdtemp, writeFile, rm } = await import("node:fs/promises");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const dir = await mkdtemp(join(tmpdir(), "dsh-gate-"));
  try {
    const good = join(dir, "good.js");
    const bad = join(dir, "bad.js");
    await writeFile(good, "var x = 1;\nfunction f(a) { return a + x; }\nmodule.exports = f;\n");
    await writeFile(bad, "function f( { return 1; }\n");

    assert.equal((await checkScriptSyntax(good)).ok, true);
    const failure = await checkScriptSyntax(bad);
    assert.equal(failure.ok, false);
    assert.ok(failure.error.length > 0, "a syntax error must carry a message");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("checkScriptSyntax does not execute the file", async () => {
  const { mkdtemp, writeFile, rm } = await import("node:fs/promises");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const dir = await mkdtemp(join(tmpdir(), "dsh-gate-"));
  try {
    const file = join(dir, "sideeffect.js");
    await writeFile(file, "require('this-module-does-not-exist');\n");
    assert.equal((await checkScriptSyntax(file)).ok, true, "an unresolvable require must not fail a syntax check");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("collectScripts skips vendored and generated trees", async () => {
  const root = new URL("..", import.meta.url).pathname;
  const files = await collectScripts(root);
  assert.ok(files.length > 0, "expected to find first-party scripts");
  assert.equal(
    files.some((file) => file.includes("/node_modules/") || file.includes("/3rdparty/")),
    false,
    "vendored trees must be excluded",
  );
});

test("buildSeat derives countMap from the tile list", () => {
  const seat = buildSeat([0, 0, 5]);
  assert.deepEqual(seat.countMap, { 0: 2, 5: 1 });
  assert.deepEqual(seat.holds, [0, 0, 5]);
  assert.deepEqual(seat.tingMap, {});
});
