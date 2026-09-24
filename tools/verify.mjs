#!/usr/bin/env node
/**
 * The verification gate for this repository.
 *
 * Every change — by a human or an AI agent — is expected to pass this before it
 * is considered done. It is dependency-free by design: the gate itself needs no
 * `npm install`, and the server's `node_modules` (installed from
 * `server/yarn.lock`) are skipped by name rather than read, so a gate that runs
 * anywhere is a gate everyone runs.
 *
 * Usage:
 *   node tools/verify.mjs              run every check
 *   node tools/verify.mjs --list       list check names
 *   node tools/verify.mjs --only=syntax,protocol
 *   node tools/verify.mjs --json       machine-readable summary
 *   node tools/verify.mjs --verbose    print every file considered
 *
 * Exit code 0 means every check passed; 1 means at least one check failed.
 */

import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { collectScripts, checkScriptSyntax, displayPath, exists, findStrayServerJavaScript, findStrayClientJavaScript } from "./lib/syntax.mjs";
import { checkClientAssetIntegrity } from "./lib/assets.mjs";
import { checkHarness } from "./lib/harness.mjs";
import { checkProtocol } from "./lib/protocol.mjs";
import { runSmoke } from "./lib/smoke.mjs";
import { checkPython } from "./lib/python.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

const options = {
  json: process.argv.includes("--json"),
  verbose: process.argv.includes("--verbose"),
  list: process.argv.includes("--list"),
  only: (process.argv.find((arg) => arg.startsWith("--only=")) ?? "").replace("--only=", ""),
};

const useColor = process.stdout.isTTY === true && !options.json;
const paint = (code, text) => (useColor ? `\u001B[${code}m${text}\u001B[0m` : text);
const green = (text) => paint(32, text);
const red = (text) => paint(31, text);
const dim = (text) => paint(2, text);
const bold = (text) => paint(1, text);

/**
 * Check: every first-party `.js` / `.ts` file parses.
 * @returns {Promise<object>} check result.
 */
async function syntaxCheck() {
  const clientFiles = await collectScripts(join(ROOT, "client"), { exclude: ["/assets/scripts/3rdparty/"] });
  const serverFiles = await collectScripts(join(ROOT, "server"));
  const toolFiles = await collectScripts(join(ROOT, "tools"));
  const targets = [...clientFiles, ...serverFiles, ...toolFiles];

  const failures = [];
  const skipped = [];
  for (const file of targets) {
    const result = await checkScriptSyntax(file);
    if (!result.ok) failures.push(`${displayPath(ROOT, file)}\n    ${result.error}`);
    else if (result.skipped === true) skipped.push(displayPath(ROOT, file));
    else if (options.verbose) console.log(dim(`    ok  ${displayPath(ROOT, file)}`));
  }

  // A skip is not a failure, but it must never look like a pass either: on a Node
  // too old to strip types the .ts half of the repository is simply not checked,
  // and the summary says so out loud.
  for (const file of skipped) console.log(dim(`    ⊘ skipped ${file}`));

  // `server/` must not contain first-party `.js` at all: Node resolves `.js`
  // before `.ts`, so a leftover copy is the file that actually runs.
  const stray = await findStrayServerJavaScript(ROOT);
  for (const file of stray) {
    failures.push(
      `${displayPath(ROOT, file)}\n    server/ 已全量迁移到 TypeScript：这里残留了一方 .js。Node 会优先加载 .js 而不是同名 .ts，` +
        `旧副本会掩盖真实行为；编译产物只该出现在 dist/（yarn build 生成）。请删除这个文件。`,
    );
  }

  // `client/` is TypeScript as well; a leftover `.js` would sit beside its `.ts`
  // twin and nobody could tell which one Creator imported.
  const strayClient = await findStrayClientJavaScript(ROOT);
  for (const file of strayClient) {
    failures.push(
      `${displayPath(ROOT, file)}\n    client/ 也已全量迁移到 TypeScript：请把同名的 .ts 补全并删除这个 .js` +
        `（vendored 的 assets/scripts/3rdparty/ 不在此列）。`,
    );
  }

  // Renaming a script is only safe when its `.meta` (and therefore its uuid) comes
  // along: a scene refers to a script component by compressed uuid, so a rebuilt
  // meta silently drops the component from the node. `tsc` cannot see this.
  const assets = await checkClientAssetIntegrity(ROOT);
  for (const failure of assets.failures) failures.push(failure);

  return {
    name: "syntax",
    title: "Source syntax & client script bindings",
    ok: failures.length === 0,
    summary:
      `${targets.length - skipped.length} files parsed` +
      (skipped.length === 0 ? "" : `, ${skipped.length} skipped (Node too old for .ts)`) +
      (stray.length === 0 ? "" : `, ${stray.length} stray server .js`) +
      (strayClient.length === 0 ? "" : `, ${strayClient.length} stray client .js`) +
      (assets.failures.length === 0 ? "" : `, ${assets.failures.length} broken script bindings`),
    failures,
  };
}

/**
 * Check: `server/` type-checks with `strict: true`, and does not escape the type
 * system with `any` / `@ts-ignore`.
 *
 * The migration contract is "strict types, as little `any` as possible", so the
 * escape hatches are audited mechanically instead of being left to review:
 * `any` in any form, `@ts-ignore` and `@ts-expect-error` all count as failures.
 * The audit is pure text processing, so it runs even when the compiler is
 * missing — type checking itself needs TypeScript from `server/node_modules`,
 * which `yarn install` provides. When it is absent that half reports itself as
 * *skipped* (never as passed) while the audit result still stands.
 *
 * @returns {Promise<object>} check result.
 */
async function typesCheck() {
  const audit = await auditNoAnyEscapeHatches();

  const tsc = join(ROOT, "server/node_modules/typescript/bin/tsc");
  if (!(await exists(tsc))) {
    return {
      name: "types",
      title: "TypeScript strict type-check",
      ok: audit.failures.length === 0,
      skipped: audit.failures.length === 0,
      summary:
        audit.failures.length === 0
          ? `skipped — ${audit.files} 个 .ts 已通过 no-any 审计（client 另查 cc.Class）；未找到 server/node_modules/typescript（先 cd server && yarn install）`
          : `${audit.failures.length} 处类型检查逃生舱或客户端脚本契约违规`,
      failures: audit.failures,
    };
  }

  // Both first-party trees are TypeScript and share one compiler. `server/` keeps
  // its own tsconfig (emits to dist/); `client/`'s tsconfig only serves this
  // check and the editor — Creator compiles the client itself.
  const projects = [
    { label: "server/", cwd: join(ROOT, "server") },
    { label: "client/", cwd: join(ROOT, "client") },
  ];
  const failures = [...audit.failures];
  const status = [];
  for (const project of projects) {
    const run = await runTypeScript(tsc, project.cwd);
    status.push(`${project.label}${run.code === 0 ? " ok" : " FAIL"}`);
    if (run.code !== 0) {
      failures.push(`\n${project.label} tsc --noEmit（strict）报错：\n${run.output}`);
    }
  }

  const auditSummary =
    audit.failures.length === 0
      ? `${audit.files} 个 .ts 无 any / 类型逃生舱（含 client 的 ${audit.clientFiles} 个：无 cc.Class、都有 module.exports）`
      : `${audit.failures.length} 处类型检查逃生舱或客户端脚本契约违规`;
  return {
    name: "types",
    title: "TypeScript strict type-check",
    ok: failures.length === 0,
    summary: `${auditSummary}；tsc（strict）：${status.join("、")}`,
    failures,
  };
}

/**
 * Run the repository's TypeScript compiler against one project.
 * @param {string} tsc absolute path to the compiler entry point.
 * @param {string} cwd project directory holding `tsconfig.json`.
 * @returns {Promise<{ code: number, output: string }>} exit code and trimmed output.
 */
async function runTypeScript(tsc, cwd) {
  const { spawn } = await import("node:child_process");
  const run = await new Promise((resolve) => {
    const child = spawn(process.execPath, [tsc, "--noEmit", "-p", "tsconfig.json"], {
      cwd,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let output = "";
    child.stdout.on("data", (chunk) => (output += chunk));
    child.stderr.on("data", (chunk) => (output += chunk));
    child.on("close", (code) => resolve({ code, output }));
  });
  return { code: run.code, output: run.output.split("\n").filter((line) => line.trim() !== "").slice(0, 60).join("\n") };
}

/** Type-system escape hatches this repository does not accept. */
const FORBIDDEN_TYPE_PATTERNS = [
  { pattern: /:\s*any\b/, label: "显式 any 类型" },
  { pattern: /\bas\s+any\b/, label: "as any 断言" },
  { pattern: /<any>/, label: "<any> 断言" },
  { pattern: /@ts-ignore\b/, label: "@ts-ignore" },
  { pattern: /@ts-expect-error\b/, label: "@ts-expect-error" },
];

/**
 * Client-only source rules.
 *
 * Components are ES6 classes with `cc._decorator` decorators
 * (`@ccclass` / `@property`); the old `cc.Class({...})` form is gone.
 * Nothing else would catch a comeback: `creator.d.ts` still declares
 * `cc.Class`, so `tsc` is happy with it and the old and new spellings both run.
 */
const FORBIDDEN_CLIENT_PATTERNS = [
  {
    pattern: /(?<![.\w])cc\.Class\s*\(/,
    label: "cc.Class 写法（客户端组件请用 ES6 class + @ccclass / @property）",
  },
];

/**
 * Audit every first-party `.ts` file for explicit `any` and type-check escapes,
 * and the client tree for the retired `cc.Class` spelling.
 *
 * Comments are blanked out (newlines kept so line numbers stay true) before
 * matching, so prose about `any` — including the rules themselves — is not
 * mistaken for a violation.
 *
 * @returns {Promise<{ files: number, clientFiles: number, failures: string[] }>} audit outcome.
 */
async function auditNoAnyEscapeHatches() {
  const { readFile } = await import("node:fs/promises");
  const serverFiles = await collectScripts(join(ROOT, "server"));
  const clientFiles = await collectScripts(join(ROOT, "client"), {
    exclude: ["/assets/scripts/3rdparty/"],
  });
  const files = [...serverFiles, ...clientFiles].filter((file) => file.endsWith(".ts"));
  const clientRoot = join(ROOT, "client");
  const failures = [];

  for (const file of files) {
    const source = await readFile(file, "utf8");
    const blanked = source
      .replace(/\/\*[\s\S]*?\*\//g, (match) => match.replace(/[^\n]/g, " "))
      .replace(/\/\/[^\n]*/g, "");
    const patterns = file.startsWith(clientRoot)
      ? [...FORBIDDEN_TYPE_PATTERNS, ...FORBIDDEN_CLIENT_PATTERNS]
      : FORBIDDEN_TYPE_PATTERNS;
    blanked.split("\n").forEach((line, index) => {
      for (const { pattern, label } of patterns) {
        if (pattern.test(line)) {
          failures.push(`${displayPath(ROOT, file)}:${index + 1} 出现${label}：${line.trim()}`);
        }
      }
    });

    // Creator's loader returns `module.exports`, and `export default class X`
    // compiles (tsc, `module: commonjs`) to `exports.default = X` — so a
    // component without the explicit assignment makes every `require("X")`
    // hand back `{__esModule, default}`. The runtime error is
    // "X is not a constructor", and neither tsc nor the syntax check sees it.
    if (file.startsWith(clientRoot)) {
      const exported = /export\s+default\s+class\s+([A-Za-z_$][\w$]*)/.exec(blanked);
      if (exported) {
        const name = exported[1];
        if (!new RegExp(`(^|\\n)\\s*module\\.exports\\s*=\\s*${name}\\s*;`).test(blanked)) {
          failures.push(
            `${displayPath(ROOT, file)} 缺少 \`module.exports = ${name};\`：` +
              `Creator 的 require("${name}") 取的是 module.exports，export default 只会编译成 exports.default`,
          );
        }
      }
    }
  }

  return { files: files.length, clientFiles: clientFiles.length, failures };
}

/**
 * Check: the DSH harness can actually discover the instruction files and skills.
 * @returns {Promise<object>} check result.
 */
async function harnessCheck() {
  const result = await checkHarness(ROOT);
  return {
    name: "harness",
    title: "Harness contract",
    ok: result.ok,
    summary: result.notes.join(", "),
    failures: result.problems,
  };
}

/**
 * Check: the Socket.IO event vocabulary matches on both sides.
 * @returns {Promise<object>} check result.
 */
async function protocolCheck() {
  // Scan every first-party server file rather than a fixed list: the game logic
  // lives in two parallel managers and pushes are spread across both.
  const serverFiles = await collectScripts(join(ROOT, "server"));
  const clientFiles = await collectScripts(join(ROOT, "client"), {
    exclude: ["/assets/scripts/3rdparty/"],
  });

  const result = await checkProtocol(ROOT, serverFiles, clientFiles, join(ROOT, "docs/ai-native/protocol.md"));
  const failures = [];
  for (const event of result.unhandled) failures.push(`server pushes '${event}' but no client handler registers it`);
  for (const event of result.unsent) failures.push(`client handles '${event}' but no server push sends it`);
  for (const event of result.undocumented) {
    failures.push(`server pushes '${event}' but docs/ai-native/protocol.md §1 does not list it`);
  }
  for (const event of result.stale) {
    failures.push(`docs/ai-native/protocol.md §1 lists '${event}' but no server push sends it`);
  }

  return {
    name: "protocol",
    title: "Socket.IO event vocabulary",
    ok: result.ok,
    summary: `${result.serverCount} server events, ${result.clientCount} client handlers, reference table in sync`,
    failures,
  };
}

/**
 * Check: pure server logic still behaves correctly.
 * @returns {Promise<object>} check result.
 */
async function smokeCheck() {
  const result = await runSmoke(ROOT);
  if (result.error !== undefined) {
    return {
      name: "smoke",
      title: "Behavioural smoke tests",
      ok: false,
      summary: "could not run",
      failures: [result.error],
    };
  }

  const failures = result.checks
    .filter((entry) => !entry.ok)
    .map((entry) => `${entry.name}${entry.detail === undefined ? "" : `\n    ${entry.detail}`}`);
  for (const entry of result.checks) {
    if (options.verbose) console.log(entry.ok ? dim(`    ok  ${entry.name}`) : red(`    FAIL ${entry.name}`));
  }

  return {
    name: "smoke",
    title: "Behavioural smoke tests",
    ok: result.ok,
    summary: `${result.checks.filter((entry) => entry.ok).length}/${result.checks.length} assertions passed`,
    failures,
  };
}

/**
 * Check: the gate's own parsers behave as documented.
 * @returns {Promise<object>} check result.
 */
async function selfTestCheck() {
  const { spawn } = await import("node:child_process");
  return await new Promise((resolve) => {
    const child = spawn(process.execPath, ["--test", join(ROOT, "tools/selftest.test.mjs")], {
      cwd: ROOT,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let output = "";
    child.stdout.on("data", (chunk) => (output += chunk));
    child.stderr.on("data", (chunk) => (output += chunk));
    child.on("close", (code) => {
      // Node's test reporter prefixes its summary lines with either '#' or 'ℹ'
      // depending on version and TTY, so accept both.
      const passMatch = /^[#\u2139]\s*pass (\d+)$/m.exec(output);
      const failMatch = /^[#\u2139]\s*fail (\d+)$/m.exec(output);
      const passed = passMatch === null ? 0 : Number(passMatch[1]);
      const failed = failMatch === null ? 0 : Number(failMatch[1]);
      resolve({
        name: "selftest",
        title: "Verification tooling self-test",
        ok: code === 0,
        summary: `${passed} passed, ${failed} failed`,
        failures: code === 0 ? [] : [output.trim().split("\n").slice(-25).join("\n")],
      });
    });
  });
}

/**
 * Check: the Python server tree parses and its offline tests pass.
 * @returns {Promise<object>} check result.
 */
async function pythonCheck() {
  return await checkPython(ROOT, { verbose: options.verbose });
}

const CHECKS = [
  ["syntax", syntaxCheck],
  ["types", typesCheck],
  ["harness", harnessCheck],
  ["protocol", protocolCheck],
  ["smoke", smokeCheck],
  ["python", pythonCheck],
  ["selftest", selfTestCheck],
];

if (options.list) {
  for (const [name, fn] of CHECKS) console.log(`${name}\t${fn.name}`);
  process.exit(0);
}

const selected = options.only === "" ? CHECKS : CHECKS.filter(([name]) => options.only.split(",").includes(name));

if (selected.length === 0) {
  console.error(red(`No check matched --only=${options.only}`));
  console.error(`Available: ${CHECKS.map(([name]) => name).join(", ")}`);
  process.exit(1);
}

const results = [];
for (const [name, run] of selected) {
  if (!options.json) process.stdout.write(`\n${bold("▶")} running ${bold(name)} check…`);
  let result;
  try {
    result = await run();
  } catch (error) {
    // A check that throws is a failed check, never a crashed gate: the point is
    // to report the problem rather than to abort on it.
    result = {
      name,
      title: name,
      ok: false,
      summary: "check crashed",
      failures: [error instanceof Error ? (error.stack ?? error.message) : String(error)],
    };
  }
  results.push(result);
  if (!options.json) {
    const marker = result.ok ? (result.skipped === true ? dim("⊘") : green("✔")) : red("✘");
    process.stdout.write(`\r${marker} ${bold(result.title)} — ${result.summary}\n`);
    for (const failure of result.failures) console.log(`  ${red("•")} ${failure.replace(/\n/g, "\n    ")}`);
  }
}

const failed = results.filter((result) => !result.ok);

if (options.json) {
  console.log(JSON.stringify({ ok: failed.length === 0, results }, null, 2));
} else {
  const line = "─".repeat(60);
  console.log(`\n${line}`);
  if (failed.length === 0) {
    console.log(green(`✔ gate passed`) + dim(`  (${results.length} checks)`));
  } else {
    console.log(red(`✘ gate failed`) + `  ${failed.length}/${results.length} checks failed: ${failed.map((r) => r.name).join(", ")}`);
    console.log(dim("Fix the failures above and run `npm run verify` again."));
  }
}

process.exit(failed.length === 0 ? 0 : 1);
