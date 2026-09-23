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

import { collectScripts, checkScriptSyntax, displayPath } from "./lib/syntax.mjs";
import { checkHarness } from "./lib/harness.mjs";
import { checkProtocol } from "./lib/protocol.mjs";
import { runSmoke } from "./lib/smoke.mjs";

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
 * Check: every first-party `.js` file parses.
 * @returns {Promise<object>} check result.
 */
async function syntaxCheck() {
  const clientFiles = await collectScripts(join(ROOT, "client"), { exclude: ["/assets/scripts/3rdparty/"] });
  const serverFiles = await collectScripts(join(ROOT, "server"));
  const toolFiles = await collectScripts(join(ROOT, "tools"));
  const targets = [...clientFiles, ...serverFiles, ...toolFiles];

  const failures = [];
  for (const file of targets) {
    const result = await checkScriptSyntax(file);
    if (!result.ok) failures.push(`${displayPath(ROOT, file)}\n    ${result.error}`);
    else if (options.verbose) console.log(dim(`    ok  ${displayPath(ROOT, file)}`));
  }

  return {
    name: "syntax",
    title: "JavaScript syntax",
    ok: failures.length === 0,
    summary: `${targets.length} files parsed`,
    failures,
  };
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

const CHECKS = [
  ["syntax", syntaxCheck],
  ["harness", harnessCheck],
  ["protocol", protocolCheck],
  ["smoke", smokeCheck],
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
    process.stdout.write(`\r${result.ok ? green("✔") : red("✘")} ${bold(result.title)} — ${result.summary}\n`);
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
