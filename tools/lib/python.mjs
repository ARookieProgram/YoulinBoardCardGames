/**
 * Check: the Python server tree (`server-python/`) parses and its tests pass.
 *
 * `server-python/` is the Python 3.14 rewrite of the Node server trio. It is a
 * separate runtime, so the existing `syntax` and `types` checks — which are
 * built around `.ts` files under `server/` and `client/` — never look at it.
 * Without this check a broken Python file would sail through the gate.
 *
 * The check has two halves, mirroring how `types` reports a missing `tsc`:
 *
 *   1. **AST parse** every first-party `.py` file. Zero dependencies, always
 *      runs. Parsing (not importing) keeps it side-effect free: importing
 *      `game_server.app` would bind sockets.
 *   2. **Run the offline unit tests** (`tests/`, stdlib `unittest`) when a
 *      Python interpreter with the runtime dependencies is available. Missing
 *      dependencies are reported as `skipped` with the reason, never as a pass.
 *
 * The interpreter is discovered in this order: `server-python/.venv/bin/python`
 * (what `AGENTS.md` tells contributors to create), then `python3` on PATH.
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";

/** Directories inside `server-python/` that hold no first-party source. */
const EXCLUDED_DIRS = new Set([".venv", "__pycache__", "logs", ".run", "node_modules"]);

/**
 * Collect every first-party `.py` file under a directory.
 *
 * @param {string} directory absolute directory to walk.
 * @returns {Promise<string[]>} absolute file paths.
 */
async function collectPythonFiles(directory) {
  const found = [];
  let entries;
  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch {
    return found;
  }
  for (const entry of entries) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      if (EXCLUDED_DIRS.has(entry.name)) continue;
      found.push(...(await collectPythonFiles(path)));
    } else if (entry.isFile() && entry.name.endsWith(".py")) {
      found.push(path);
    }
  }
  return found;
}

/**
 * Find a usable Python interpreter.
 *
 * @param {string} pythonRoot absolute path to `server-python/`.
 * @returns {{ command: string, label: string } | null} interpreter, or null.
 */
function findInterpreter(pythonRoot) {
  const venv = join(pythonRoot, ".venv", "bin", "python");
  if (existsSync(venv)) return { command: venv, label: "server-python/.venv/bin/python" };
  return { command: "python3", label: "python3" };
}

/**
 * Run one command and capture its output.
 *
 * @param {string} command executable.
 * @param {string[]} args arguments.
 * @param {string} cwd working directory.
 * @returns {Promise<{ code: number, output: string, spawnError?: string }>}
 */
function run(command, args, cwd) {
  return new Promise((resolve) => {
    const child = spawn(command, args, { cwd, stdio: ["ignore", "pipe", "pipe"] });
    let output = "";
    child.stdout.on("data", (chunk) => (output += chunk));
    child.stderr.on("data", (chunk) => (output += chunk));
    child.on("error", (error) => resolve({ code: -1, output: "", spawnError: String(error.message ?? error) }));
    child.on("close", (code) => resolve({ code: code ?? -1, output }));
  });
}

/**
 * Check: `server-python/` parses, and its offline tests pass.
 *
 * @param {string} root repository root.
 * @param {{ verbose?: boolean }} [options] gate options.
 * @returns {Promise<object>} check result.
 */
export async function checkPython(root, options = {}) {
  const pythonRoot = join(root, "server-python");
  if (!existsSync(pythonRoot)) {
    return {
      name: "python",
      title: "Python server syntax + offline tests",
      ok: true,
      skipped: true,
      summary: "skipped — server-python/ 不存在",
      failures: [],
    };
  }

  const interpreter = findInterpreter(pythonRoot);
  const files = await collectPythonFiles(pythonRoot);
  if (files.length === 0) {
    return {
      name: "python",
      title: "Python server syntax + offline tests",
      ok: false,
      summary: "server-python/ 下没有任何 .py 文件",
      failures: ["server-python/ 存在但一个 Python 源文件都没有，目录结构可能被破坏。"],
    };
  }

  // Half 1: parse every file without importing it. `ast.parse` is exactly the
  // "does this file even parse" question, with no side effects — importing
  // `game_server.app` would try to bind the service ports.
  const parseScript = [
    "import ast, sys",
    "bad = []",
    "for path in sys.argv[1:]:",
    "    try:",
    "        ast.parse(open(path, encoding='utf-8').read(), filename=path)",
    "    except SyntaxError as e:",
    "        bad.append(f'{path}:{e.lineno}: {e.msg}')",
    "print('\\n'.join(bad))",
  ].join("\n");

  const parsed = await run(interpreter.command, ["-c", parseScript, ...files], root);
  if (parsed.spawnError !== undefined) {
    return {
      name: "python",
      title: "Python server syntax + offline tests",
      ok: true,
      skipped: true,
      summary: `skipped — 找不到 Python 解释器（${interpreter.label}）`,
      failures: [],
    };
  }
  const syntaxFailures = parsed.output
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");

  // Half 2: run the offline unit tests. They need aiohttp / aiomysql, so a bare
  // `python3` without them reports the check as *skipped* (never as passed),
  // exactly like the `types` check does when `tsc` is not installed.
  const deps = await run(interpreter.command, ["-c", "import aiohttp, aiomysql"], pythonRoot);
  if (deps.code !== 0) {
    return {
      name: "python",
      title: "Python server syntax + offline tests",
      ok: syntaxFailures.length === 0,
      skipped: syntaxFailures.length === 0,
      summary:
        syntaxFailures.length === 0
          ? `skipped — ${files.length} 个 .py 已通过解析；${interpreter.label} 缺少运行时依赖` +
            `（cd server-python && .venv/bin/pip install -r requirements.txt），离线测试未运行`
          : `${syntaxFailures.length} 个 .py 存在语法错误`,
      failures: syntaxFailures.map((line) => `语法错误：${line}`),
    };
  }

  const tested = await run(
    interpreter.command,
    ["-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"],
    pythonRoot,
  );
  const ran = /^Ran (\d+) tests?/m.exec(tested.output);
  const count = ran === null ? "?" : ran[1];
  const failures = [...syntaxFailures.map((line) => `语法错误：${line}`)];
  if (tested.code !== 0) {
    failures.push(tested.output.trim().split("\n").slice(-30).join("\n"));
  }

  const summary =
    `${files.length} 个 .py 解析通过；` +
    (tested.code === 0 ? `${count} 个离线测试通过` : `${count} 个测试中有失败`);

  if (options.verbose === true) {
    for (const file of files) console.log(`    ok  ${file.slice(root.length + 1)}`);
  }

  return {
    name: "python",
    title: "Python server syntax + offline tests",
    ok: failures.length === 0,
    summary,
    failures,
  };
}
