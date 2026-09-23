/**
 * Static syntax verification for this repository.
 *
 * Two languages are checked here, and both are checked the same way: by parsing
 * them without running them.
 *
 *  - JavaScript: the Cocos Creator 2.4.15 client and the verification tooling
 *    themselves are classic CommonJS / ES5-era scripts, compiled but never
 *    executed (`vm.Script`).
 *  - TypeScript: `repo:server/` is TypeScript since the migration described in
 *    `docs/ai-native/typescript-migration.md`. It is parsed with Node's own
 *    `module.stripTypeScriptTypes`, which erases types exactly like the compiler
 *    will — and, usefully, refuses syntax that cannot be erased (`enum`,
 *    `namespace`, `import x = require(...)`, constructor parameter properties),
 *    which is a rule this repository deliberately keeps.
 *
 * This module deliberately avoids external dependencies so it runs with no
 * `npm install` step: the TypeScript check uses a Node built-in, and if the
 * running Node is too old for it the check reports those files as *skipped*
 * rather than pretending to have verified them. Third-party trees
 * (`node_modules`, the Cocos Creator `library`/`temp` output, vendored client
 * libraries) are skipped by name, so the gate does not care how the server's own
 * dependencies are installed.
 */

import { readdir, readFile, stat } from "node:fs/promises";
import { join, relative, basename } from "node:path";
import vm from "node:vm";
import * as nodeModule from "node:module";

/** Directories that never contain first-party source. */
const SKIP_DIRS = new Set([
  ".git",
  ".dsh",
  "node_modules",
  ".yarn-cache", // yarn add 的工作区缓存；里面也可能有零散 .js，不该被当成一方源码
  "library",
  "temp",
  "local",
  "build",
  "dist",
]);

/**
 * Files that are parsed only as a template, or are intentionally not
 * standalone-parseable ECMAScript / TypeScript.
 */
const SKIP_FILE_PATTERNS = [
  /\.min\.js$/,
  /\.d\.ts$/, // 纯声明文件，没有运行时代码
  /^creator\.d\.ts$/,
  /^socket-io\.js$/, // vendored third-party client library
];

/** First-party source extensions this gate can parse. */
const SOURCE_EXTENSIONS = [".js", ".ts"];

/**
 * `module.stripTypeScriptTypes` typed as optional: it exists on Node >= 22.13 and
 * the gate must still run (and say so honestly) on older Node.
 * @type {((code: string, options?: { mode?: string, sourceUrl?: string }) => string) | null}
 */
const stripTypeScriptTypes =
  typeof nodeModule.stripTypeScriptTypes === "function" ? nodeModule.stripTypeScriptTypes : null;

/**
 * Whether this Node can parse `.ts` sources.
 * @returns {boolean} true when `.ts` files can be checked rather than skipped.
 */
export function supportsTypeScriptCheck() {
  return stripTypeScriptTypes !== null;
}

/**
 * Recursively collect first-party `.js` / `.ts` files under `root`.
 * @param {string} root absolute directory to walk.
 * @param {{ include?: RegExp, exclude?: string[] }} [options]
 * @returns {Promise<string[]>} absolute file paths, sorted.
 */
export async function collectScripts(root, options = {}) {
  const exclude = options.exclude ?? [];
  const found = [];

  async function walk(dir) {
    let entries;
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        if (SKIP_DIRS.has(entry.name)) continue;
        await walk(full);
        continue;
      }
      if (!entry.isFile()) continue;
      if (!SOURCE_EXTENSIONS.some((extension) => entry.name.endsWith(extension))) continue;
      if (SKIP_FILE_PATTERNS.some((pattern) => pattern.test(entry.name))) continue;
      if (options.include && !options.include.test(full)) continue;
      if (exclude.some((prefix) => full.includes(prefix))) continue;
      found.push(full);
    }
  }

  await walk(root);
  return found.sort();
}

/**
 * Parse one file without executing it.
 *
 * JavaScript goes through `vm.Script` (classic script, matching how both the
 * server and Cocos Creator load these files). TypeScript goes through Node's
 * type eraser, which both validates the syntax and enforces that the file only
 * uses erasable TypeScript.
 *
 * @param {string} file absolute path.
 * @returns {Promise<{ file: string, ok: boolean, error?: string, skipped?: boolean, reason?: string }>}
 */
export async function checkScriptSyntax(file) {
  const source = await readFile(file, "utf8");

  if (file.endsWith(".ts")) {
    if (stripTypeScriptTypes === null) {
      return {
        file,
        ok: true,
        skipped: true,
        reason: "当前 Node 没有 module.stripTypeScriptTypes（需要 >= 22.13），.ts 未校验",
      };
    }
    try {
      stripTypeScriptTypes(source, { mode: "strip", sourceUrl: file });
      return { file, ok: true };
    } catch (error) {
      return {
        file,
        ok: false,
        error: `${error instanceof Error ? error.message : String(error)}\n    .ts 只允许可擦除语法：不要用 enum / namespace / import x = require() / 构造函数参数属性（见 docs/ai-native/typescript-migration.md §2）`,
      };
    }
  }

  try {
    // `new vm.Script` compiles without executing, so requiring a module that
    // needs a live MySQL connection (or any native addon) never has to happen.
    new vm.Script(source, { filename: file });
    return { file, ok: true };
  } catch (error) {
    return { file, ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

/**
 * First-party `.js` files left behind under `server/`.
 *
 * `server/` is TypeScript now: every source is a `.ts`, and runnable JavaScript
 * exists only in the git-ignored `dist/` that `tsc` produces. A stray `.js` next
 * to its `.ts` twin is exactly how a half-finished migration hides — Node's
 * resolver prefers `.js`, so the stale copy would be the one actually loaded
 * while everyone reads the `.ts` source.
 *
 * @param {string} root repository root.
 * @returns {Promise<string[]>} absolute paths of stray server JavaScript, sorted.
 */
export async function findStrayServerJavaScript(root) {
  const files = await collectScripts(join(root, "server"));
  return files.filter((file) => file.endsWith(".js"));
}

/**
 * Report a file path relative to the repository root using `/` separators.
 * @param {string} root repository root.
 * @param {string} file absolute path.
 * @returns {string} display path.
 */
export function displayPath(root, file) {
  return relative(root, file).split("\\").join("/");
}

/** @param {string} path @returns {Promise<boolean>} whether path exists. */
export async function exists(path) {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

export { basename };
