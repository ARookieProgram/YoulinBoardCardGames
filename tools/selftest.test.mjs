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
import { collectScripts, checkScriptSyntax, findStrayServerJavaScript, findStrayClientJavaScript, supportsTypeScriptCheck } from "./lib/syntax.mjs";
import { compressUuid, checkClientAssetIntegrity } from "./lib/assets.mjs";
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

test("checkScriptSyntax checks TypeScript with the type eraser, not the JS parser", async (t) => {
  if (!supportsTypeScriptCheck()) {
    t.skip("this Node has no module.stripTypeScriptTypes");
    return;
  }
  const { mkdtemp, writeFile, rm } = await import("node:fs/promises");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const dir = await mkdtemp(join(tmpdir(), "dsh-gate-ts-"));
  try {
    const good = join(dir, "good.ts");
    const bad = join(dir, "bad.ts");
    const nonErasable = join(dir, "enum.ts");
    await writeFile(good, "export function f(a: string): number { return a.length; }\n");
    await writeFile(bad, "export function f(a: string): number { return a.length; \n");
    // `enum` is not erasable, and the migration rule is that server/ only uses
    // erasable TypeScript, so the gate must reject it.
    await writeFile(nonErasable, "export enum E { A, B }\n");

    assert.equal((await checkScriptSyntax(good)).ok, true, "valid TypeScript must pass");
    const broken = await checkScriptSyntax(bad);
    assert.equal(broken.ok, false, "a TypeScript syntax error must fail");
    assert.ok(broken.error.length > 0, "a syntax error must carry a message");
    const enumResult = await checkScriptSyntax(nonErasable);
    assert.equal(enumResult.ok, false, "non-erasable TypeScript must fail");
    assert.match(enumResult.error, /可擦除语法/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("findStrayServerJavaScript reports leftover .js under server/ only", async () => {
  // `server/` is TypeScript: a `.js` beside its `.ts` twin would win Node's
  // resolver and silently run the stale copy, so the gate must see it. Generated
  // output (dist/) and vendored trees (node_modules/) are not stray.
  const { mkdtemp, writeFile, mkdir, rm } = await import("node:fs/promises");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const root = await mkdtemp(join(tmpdir(), "dsh-gate-stray-"));
  try {
    await mkdir(join(root, "server", "utils"), { recursive: true });
    await mkdir(join(root, "server", "dist"), { recursive: true });
    await mkdir(join(root, "server", "node_modules"), { recursive: true });
    await writeFile(join(root, "server", "utils", "a.ts"), "export const a = 1;\n");
    await writeFile(join(root, "server", "utils", "a.js"), "exports.a = 1;\n");
    await writeFile(join(root, "server", "utils", "b.ts"), "export const b = 1;\n");
    await writeFile(join(root, "server", "dist", "a.js"), "exports.a = 1;\n");
    await writeFile(join(root, "server", "node_modules", "c.js"), "module.exports = 1;\n");

    const stray = await findStrayServerJavaScript(root);
    assert.deepEqual(
      stray.map((file) => file.slice(root.length + 1)),
      ["server/utils/a.js"],
      "only first-party .js under server/ counts",
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("findStrayClientJavaScript ignores the vendored 3rdparty tree", async () => {
  // The client is TypeScript too, but two trees must keep their `.js`:
  // `assets/scripts/3rdparty/` (vendored) and `assets/migration/` (generated by
  // Creator itself). Only first-party leftovers are stray.
  const { mkdtemp, writeFile, mkdir, rm } = await import("node:fs/promises");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const root = await mkdtemp(join(tmpdir(), "dsh-gate-stray-client-"));
  try {
    await mkdir(join(root, "client", "assets", "scripts", "components"), { recursive: true });
    await mkdir(join(root, "client", "assets", "scripts", "3rdparty"), { recursive: true });
    await mkdir(join(root, "client", "assets", "migration"), { recursive: true });
    await mkdir(join(root, "client", "library"), { recursive: true });
    await writeFile(join(root, "client", "assets", "scripts", "a.ts"), "export const a = 1;\n");
    await writeFile(join(root, "client", "assets", "scripts", "a.js"), "cc.Class({});\n");
    await writeFile(join(root, "client", "assets", "scripts", "components", "b.ts"), "export const b = 1;\n");
    await writeFile(join(root, "client", "assets", "scripts", "3rdparty", "socket-io.js"), "module.exports = 1;\n");
    await writeFile(join(root, "client", "assets", "migration", "use_v2.0.x_cc.Toggle_event.js"), "module.exports = 1;\n");
    await writeFile(join(root, "client", "library", "c.js"), "module.exports = 1;\n");

    const stray = await findStrayClientJavaScript(root);
    assert.deepEqual(
      stray.map((file) => file.slice(root.length + 1)),
      ["client/assets/scripts/a.js"],
      "only first-party .js under client/assets/scripts/ counts",
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("compressUuid reproduces the id Cocos writes into scene files", () => {
  // 取自本仓库：client/assets/scripts/BGScaler.js.meta 的 uuid 在场景里就是这个 __type__。
  assert.equal(compressUuid("3601713f-585e-4c27-8f68-c10a63e89b02"), "36017E/WF5MJ49owQpj6JsC");
});

test("checkClientAssetIntegrity catches a half-done .js -> .ts rename", async () => {
  const { mkdtemp, writeFile, mkdir, rm } = await import("node:fs/promises");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const root = await mkdtemp(join(tmpdir(), "dsh-gate-assets-"));
  try {
    const scripts = join(root, "client", "assets", "scripts");
    const scenes = join(root, "client", "assets", "scenes");
    await mkdir(scripts, { recursive: true });
    await mkdir(scenes, { recursive: true });

    // 正常改名：Foo.js -> Foo.ts，meta 跟着改、uuid 保留，场景引用仍然解析得到。
    const fooUuid = "3601713f-585e-4c27-8f68-c10a63e89b02";
    await writeFile(join(scripts, "Foo.ts"), "export { };\n");
    await writeFile(join(scripts, "Foo.ts.meta"), JSON.stringify({ uuid: fooUuid }));
    await writeFile(
      join(scenes, "s.fire"),
      `{"__type__": "cc.Node"}\n{"__type__": "${compressUuid(fooUuid)}"}\n`,
    );
    let result = await checkClientAssetIntegrity(root);
    assert.deepEqual(result.failures, [], "a correct rename must pass");

    // 漏改 meta：Bar.ts 没有 .meta，还留下一个孤儿 Bar.js.meta；场景引用了一个不存在的脚本 id。
    await writeFile(join(scripts, "Bar.ts"), "export { };\n");
    await writeFile(join(scripts, "Bar.js.meta"), JSON.stringify({ uuid: "ed057060-a7c1-4794-96c6-23e96300dedd" }));
    await writeFile(join(scenes, "t.fire"), `{"__type__": "AAAAAaaaaaaaaaaaaaaaaaa"}\n`);
    result = await checkClientAssetIntegrity(root);
    const report = result.failures.join("\n");
    assert.equal(result.failures.length, 3, "missing meta, orphan meta and dangling __type__ must all be reported");
    assert.match(report, /Bar\.ts/);
    assert.match(report, /Bar\.js\.meta/);
    assert.match(report, /AAAAAaaaaaaaaaaaaaaaaaa/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("collectScripts picks up .ts sources and skips .d.ts declarations", async () => {
  const { mkdtemp, writeFile, mkdir, rm } = await import("node:fs/promises");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const dir = await mkdtemp(join(tmpdir(), "dsh-gate-collect-"));
  try {
    await mkdir(join(dir, "src"), { recursive: true });
    await writeFile(join(dir, "src", "a.ts"), "export const a = 1;\n");
    await writeFile(join(dir, "src", "types.d.ts"), "export interface A { x: number }\n");
    await writeFile(join(dir, "src", "b.js"), "module.exports = 1;\n");
    const files = await collectScripts(dir);
    assert.deepEqual(
      files.map((file) => file.slice(dir.length + 1)).sort(),
      ["src/a.ts", "src/b.js"],
      "both languages are source, declarations are not",
    );
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
