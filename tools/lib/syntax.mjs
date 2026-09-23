/**
 * Static JavaScript syntax verification for this repository.
 *
 * Every source file in this project is classic CommonJS / ES5-era JavaScript:
 * the Cocos Creator 2.4.15 client is compiled by Creator itself, and the server
 * is plain `node`. Neither is processed by a bundler or transpiler, so a syntax
 * error is a guaranteed runtime failure and is the cheapest possible gate.
 *
 * This module deliberately avoids external dependencies so it runs with no
 * `npm install` step. Third-party trees (`node_modules`, the Cocos Creator
 * `library`/`temp` output, vendored client libraries) are skipped by name, so
 * the gate does not care how the server's own dependencies are installed.
 */

import { readdir, stat } from "node:fs/promises";
import { join, relative, basename } from "node:path";
import vm from "node:vm";

/** Directories that never contain first-party source. */
const SKIP_DIRS = new Set([
  ".git",
  ".dsh",
  "node_modules",
  "library",
  "temp",
  "local",
  "build",
  "dist",
]);

/**
 * Files that are parsed only as a template, or are intentionally not
 * standalone-parseable ECMAScript.
 */
const SKIP_FILE_PATTERNS = [
  /\.min\.js$/,
  /^creator\.d\.ts$/,
  /^socket-io\.js$/, // vendored third-party client library
];

/**
 * Recursively collect `.js` files under `root`.
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
      if (!entry.isFile() || !entry.name.endsWith(".js")) continue;
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
 * Parse one file as a classic script (not an ES module), which matches how both
 * the server and Cocos Creator load these files.
 * @param {string} file absolute path.
 * @returns {Promise<{ file: string, ok: boolean, error?: string }>}
 */
export async function checkScriptSyntax(file) {
  try {
    const source = await import("node:fs/promises").then((fs) => fs.readFile(file, "utf8"));
    // `new vm.Script` compiles without executing, so unrelated native
    // dependencies (for example the `fibers` addon) never need to load.
    new vm.Script(source, { filename: file });
    return { file, ok: true };
  } catch (error) {
    return { file, ok: false, error: error instanceof Error ? error.message : String(error) };
  }
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
