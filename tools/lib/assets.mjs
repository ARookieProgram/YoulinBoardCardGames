/**
 * Client asset-integrity verification.
 *
 * The Cocos Creator client has one binding that no compiler checks: a scene
 * (`.fire`) refers to a script component by the **compressed uuid** of the script
 * asset, not by its file name. Renaming `Foo.js` to `Foo.ts` is therefore safe
 * only when `Foo.js.meta` is renamed alongside it with its `uuid` preserved —
 * otherwise Creator imports the file as a brand new asset, the scene keeps a
 * dangling `__type__`, and the component silently disappears from the node.
 *
 * That failure mode is invisible to `tsc` (the TypeScript is fine) and invisible
 * to the syntax check (the file is not JavaScript any more), so it is checked
 * here instead:
 *
 *   1. every first-party script has the `.meta` next to it that Creator requires;
 *   2. no `Foo.js.meta` is left behind without its `Foo.js` (a half-done rename);
 *   3. every non-engine `__type__` in `assets/**\/*.fire` and `assets/**\/*.prefab`
 *      still resolves to an asset that exists.
 *
 * This module deliberately has no dependencies: it is a gate module like the
 * rest of `tools/lib/`.
 */

import { readdir, readFile } from "node:fs/promises";
import { join, relative } from "node:path";

/** Cocos's base64 alphabet for `compressUuid`. */
const BASE64_KEYS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/**
 * Compress a Cocos asset uuid the way the editor does when it serialises a
 * script component reference into a scene.
 *
 * The first 5 hex digits are kept verbatim; each following group of 3 hex digits
 * (12 bits) becomes two base64 characters. A 32-hex uuid therefore compresses to
 * 23 characters — which is exactly the shape of a script `__type__` in a `.fire`.
 *
 * @param {string} uuid uuid in canonical `8-4-4-4-12` form.
 * @returns {string} the 23-character compressed id.
 */
export function compressUuid(uuid) {
  const hex = uuid.replace(/-/g, "");
  let out = hex.slice(0, 5);
  for (let i = 5; i < 32; i += 3) {
    const value = Number.parseInt(hex.slice(i, i + 3), 16);
    out += BASE64_KEYS[value >> 6] + BASE64_KEYS[value & 63];
  }
  return out;
}

/** `__type__` values that belong to the engine rather than to a project asset. */
const ENGINE_TYPE_PATTERN = /^cc\./;
const NON_ASSET_TYPES = new Set(["TypedArray"]);

/**
 * Recursively collect files under `dir`, returning `[]` when it does not exist.
 * @param {string} dir directory to walk.
 * @param {(name: string) => boolean} accept predicate on the file name.
 * @returns {Promise<string[]>} absolute file paths.
 */
async function collect(dir, accept) {
  const found = [];
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return found;
  }
  for (const entry of entries) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      found.push(...(await collect(full, accept)));
    } else if (entry.isFile() && accept(entry.name)) {
      found.push(full);
    }
  }
  return found;
}

/**
 * Verify the client's script assets and the scene references that point at them.
 *
 * @param {string} root repository root.
 * @returns {Promise<{ checked: number, failures: string[] }>} check outcome.
 */
export async function checkClientAssetIntegrity(root) {
  const assets = join(root, "client", "assets");
  const scripts = join(assets, "scripts");
  const failures = [];

  // 1) Every first-party script needs the sibling `.meta` Creator tracks it by.
  //    `3rdparty/` is vendored and must keep its `.js`; it is excluded from the
  //    rename rules below.
  const isVendored = (file) => relative(scripts, file).startsWith("3rdparty");
  const scriptFiles = (
    await collect(scripts, (name) => name.endsWith(".ts") || name.endsWith(".js"))
  ).filter((file) => !isVendored(file));
  const allFiles = await collect(assets, () => true);
  const fileSet = new Set(allFiles);

  for (const file of scriptFiles) {
    if (!fileSet.has(`${file}.meta`)) {
      failures.push(
        `${relative(root, file)}\n    缺少同名的 .meta：Creator 靠 .meta 里的 uuid 把脚本和场景绑定在一起，` +
          `缺少它会让场景里的组件引用失效。改名时请把原 .js.meta 一起改成 .ts.meta（uuid 保持不变）。`,
      );
    }
  }

  // 2) A leftover `Foo.js.meta` without `Foo.js` is a half-finished rename.
  for (const file of allFiles) {
    if (!file.endsWith(".js.meta")) continue;
    const source = file.slice(0, -".meta".length);
    if (isVendored(file) || !source.startsWith(scripts)) continue;
    if (!fileSet.has(source)) {
      failures.push(
        `${relative(root, file)}\n    这个 .meta 的源文件已经不存在（多半是改名时漏改了 .meta）。` +
          `请把它改成同名 .ts.meta，或删掉它，否则 assets 里会留下一个孤儿资源。`,
      );
    }
  }

  // 3) Scene / prefab component references must still resolve.
  const uuidByPath = new Map();
  for (const file of allFiles) {
    if (!file.endsWith(".meta")) continue;
    try {
      const meta = JSON.parse(await readFile(file, "utf8"));
      if (typeof meta.uuid === "string") uuidByPath.set(file, meta.uuid);
    } catch {
      // 目录或资源 meta 损坏时交给 Creator 报错，这里不重复报。
    }
  }
  const compressed = new Set();
  for (const uuid of uuidByPath.values()) compressed.add(compressUuid(uuid));

  const scenes = allFiles.filter((file) => file.endsWith(".fire") || file.endsWith(".prefab"));
  for (const scene of scenes) {
    const text = await readFile(scene, "utf8");
    const missing = new Set();
    for (const match of text.matchAll(/"__type__":\s*"([^"]+)"/g)) {
      const type = match[1];
      if (ENGINE_TYPE_PATTERN.test(type) || NON_ASSET_TYPES.has(type)) continue;
      if (!compressed.has(type)) missing.add(type);
    }
    for (const type of missing) {
      failures.push(
        `${relative(root, scene)}\n    组件类型 '${type}' 在 assets 里找不到对应资源：` +
          `这个名字是某个脚本 .meta 的 uuid 压缩后的结果，说明该脚本的 .meta 被改名/重建过（uuid 变了）。`,
      );
    }
  }

  return { checked: scriptFiles.length + scenes.length, failures };
}
