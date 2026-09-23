/**
 * `cc.Class` 的类型补丁（只影响类型检查，不产生运行时代码）。
 *
 * `creator.d.ts` 里的 `cc.Class(options): Function` 有三个问题：
 *   1. 参数类型是写死的字段列表，业务里自定义的方法（`initView` 之类）会被判为多余属性；
 *   2. 返回 `Function`，`this` 在方法里退化成 any，`new Foo()` 也不可构造；
 *   3. `properties` 里的成员在运行时是**实例属性**，静态类型里却只是 `options.properties` 的值，
 *      于是 `this.xxx` 全部找不到。
 *
 * 这里追加一个泛型重载解决这三点：
 *   - `CCPropValue` 把 Creator 的属性描述符还原成实例成员类型（完整写法 `{default, type}` 取 default，
 *     简写 `foo: null as cc.Node` 直接用自身）；
 *   - `CCProps` 把这些成员摊平到 `this` 上；
 *   - `ThisType` 把 `this` 声明为「摊平后的属性 + 选项对象自身 + cc.Component」。
 *
 * `cc.Class` 的运行时行为一字未改：这些只是 `.d.ts` 里的类型。
 *
 * 注意：带 `statics` 的类（例如 `Net.js`）里，`this` 在静态方法中其实是类本身，
 * 这时在该方法上手写 `this: XXXStatics` 显式声明，不要依赖 `ThisType`。
 */
declare namespace cc {
    /** `cc.Class(...)` 返回的构造器：`new` 出来的实例带有属性与选项对象里的全部成员。 */
    interface CCClassConstructor<T extends object> {
        new (): T & cc.Component;
    }

    /** 属性描述符 → 实例成员类型：完整写法取 `default`，简写取自身。 */
    type CCPropValue<V> = V extends { default: infer D } ? D : V;

    /** 把 `properties` 描述符表摊平成实例成员类型表。 */
    type CCProps<P> = { [K in keyof P]: CCPropValue<P[K]> };

    function Class<P extends object, T extends object>(
        options: T & { properties?: P } & ThisType<CCProps<P> & T & cc.Component>,
    ): CCClassConstructor<CCProps<P> & T>;
}
