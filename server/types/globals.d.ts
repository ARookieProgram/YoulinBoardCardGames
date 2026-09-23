/**
 * 全局补丁的类型声明。
 *
 * `String.prototype.format` 由 `repo:server/utils/http.js` 在加载时挂到原型上，
 * 业务代码（`utils/db.js` 里的 11 处 SQL 模板）依赖它做 `{0} {1} …` 占位替换。
 * 迁移到 TypeScript 时保持这个运行时行为不变，只在这里补上类型。
 */

interface String {
  /**
   * 占位符替换。
   *
   * - 传单个对象：按 `{key}` 逐项替换；
   * - 传多个参数：按 `{0} {1} …` 位置替换。
   *
   * 两种形态都在原实现里存在，见 `utils/http.ts`。
   */
  format(...args: ReadonlyArray<string | number | Record<string, string | number>>): string;
}
