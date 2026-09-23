import * as path from "node:path";

import type { ServerConfigs } from "../types/config";

/**
 * 载入命令行传入的配置文件。
 *
 * 三个进程入口的用法仍然是：
 *
 *     node dist/game_server/app.js ../configs_mac.js
 *
 * 与迁移前唯一的区别是入口文件从 `game_server/app.js` 变成了 `dist/game_server/app.js`；
 * `require` 的相对路径依旧相对**入口模块所在目录**解析，所以 `../configs_mac.js`
 * 仍然指到同一份配置（编译后是 `dist/configs_mac.js`）。`start_all_mac.sh` 里的
 * `--config` 语义也因此保持不变。
 *
 * @param configPath `process.argv[2]`，可以是相对路径或绝对路径。
 * @param baseDir 调用方所在目录（传 `__dirname`），相对路径按它解析。
 * @returns 配置文件导出的三份配置。
 */
export function loadConfigs(configPath: string | undefined, baseDir: string): ServerConfigs {
  if (configPath === undefined || configPath === "") {
    throw new Error(
      "缺少配置文件参数。用法：node dist/<进程>/app.js ../configs_mac.js（见 server/AGENTS.md §1）",
    );
  }

  const resolved = path.resolve(baseDir, configPath);

  // 唯一一处无法避免的断言：模块路径来自命令行，编译器看不到它的导出。
  // 结构由 types/config.ts 的 ServerConfigs 描述，两份配置文件都用
  // `satisfies ServerConfigs` 自证，改字段时会在这两处先报错。
  const loaded: unknown = require(resolved);
  return loaded as ServerConfigs;
}
