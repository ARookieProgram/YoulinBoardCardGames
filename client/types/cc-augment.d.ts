/**
 * 引擎类型的补充声明（只影响 `tsc --noEmit` 与编辑器补全，不产生运行时代码）。
 *
 * `creator.d.ts` 是引擎公开 API 的快照，覆盖不到三类东西，都在这里补齐：
 *   1. 引擎确实有、声明文件却漏掉的成员（例如 `cc.Node.emit`、`cc.audioEngine.play`）；
 *   2. 声明文件写错形状的成员（例如 `cc.Node.EventType` 被声明成"成员全是 0 的数值枚举"，
 *      运行时其实是 `"touchstart"` 这类字符串；`cc.sys` / `cc.loader` / `cc.game` 被声明成
 *      只有实例成员的类，运行时却是拿类当单例用）；
 *   3. 本项目运行时**动态挂在节点上的自定义字段**（例如牌节点上的 `mjId`、列表项上的 `idx`）。
 *
 * 每条声明前面的注释写清了"为什么要补"，怀疑某条时先读注释，再核对引擎源码
 * （`CocosCreator.app/Contents/Resources/engine/`）。
 * 一律用 `interface` / `var` / `function` 而不是 `let` / `class`：同一成员会被多段声明合并，
 * 而 `let` / `class` 重复声明会直接报重复标识符。
 */

// ---------------------------------------------------------------------------
// cc.Node / cc.Component
// ---------------------------------------------------------------------------

declare namespace cc {
    interface Node {
        /** 派发一个本地事件给订阅者（`GameNetMgr.dispatchEvent` 用它）。 */
        emit(event: string, data?: unknown): void;

        /**
         * `creator.d.ts` 只声明成 `getComponent(typeOrClassName: Function|string): Component`，
         * 永远拿不到具体组件类型，`node.getComponent(cc.Sprite).spriteFrame` 这类老代码全部报错。
         * 这里补两个按构造器收窄的重载（两种写法都保留，引擎两种参数形态都接受）。
         */
        getComponent<T extends Component>(type: { new (): T }): T;
        getComponent<T extends Component>(type: { prototype: T }): T;

        /**
         * `creator.d.ts` 的 `on` / `off` 把 `useCapture` 写成必填，于是 `node.on('事件', fn)`
         * 这种两参写法被判成"缺参数"；补两参重载，回调参数由调用点自己标注
         * （本地事件载荷，见 `GameNetMgr.dispatchEvent` 的派发点）。
         *
         * 第二个重载收 `cc.Node.EventType`：声明文件里它是数值枚举（成员全是 0），
         * 运行时却是 `"touchstart"` 这类字符串，而老代码传的就是这个枚举值。
         */
        on<T>(type: string, callback: (param: T) => void): Function;
        on<T>(type: Node.EventType, callback: (param: T) => void): Function;
        off(type: string, callback: Function): void;

        // ---- 以下为运行时动态挂在节点上的自定义字段，不属于 Creator 的序列化属性 ----
        /** 这张牌节点的牌 id；未使用时为 null。 */
        mjId: number | null;
        /** 牌节点上的牌 id（Seat / Folds / MJGame 使用）。 */
        pai: number;
        /** 列表项 / 按钮节点上的下标（Hall / History 使用）。 */
        idx: number;
    }

    /**
     * `creator.d.ts` 的 `cc.Animation` 声明里基类写成了 `CCComponent`，而 `CCComponent`
     * 根本没有声明（`skipLibCheck` 把错误吞掉了），于是 `getComponent(cc.Animation)`
     * 推不出类型。这里把基类补成 `cc.Component` 的别名。
     */
    interface CCComponent extends cc.Component {}
    interface Animation extends cc.Component {}
}

// ---------------------------------------------------------------------------
// 引擎单例：creator.d.ts 把它们按"类"声明，只有实例成员，缺少当单例用时访问的静态成员
// ---------------------------------------------------------------------------

declare namespace cc {
    /** `cc.loader`：`HTTP.js` 用它取 XMLHttpRequest；`ImageLoader` / `AppStart` 用它加载资源。 */
    export namespace loader {
        function getXMLHttpRequest(): XMLHttpRequest;
        function load(
            resources: string | unknown[],
            progressCallback?: Function | null,
            completeCallback?: Function,
        ): void;
    }

    /** `cc.eventManager`：`Utils.addEscEvent` 用它注册键盘监听。 */
    export namespace eventManager {
        function addListener(listener: unknown, nodeOrPriority: Node | number): EventListener;
    }

    /** `KEYBOARD` 是类常量，声明文件却写成了实例成员。 */
    export namespace EventListener {
        export var KEYBOARD: number;
    }

    /** `cc.game`：`Net` 监听 `EVENT_HIDE`，`Utils.addEscEvent` 调用 `end()`。 */
    interface Game {
        on(type: string, callback: (...args: unknown[]) => void, target?: unknown): unknown;
        end(): void;
    }

    /** `cc.audioEngine` 是单例，这些方法在 `creator.d.ts` 的 `class audioEngine` 里完全缺失。 */
    namespace audioEngine {
        var play: (clip: string, loop: boolean, volume: number) => number;
        var stop: (audioID: number) => void;
        var pause: (audioID: number) => void;
        var resume: (audioID: number) => void;
        var setVolume: (audioID: number, volume: number) => void;
        var pauseAll: () => void;
        var resumeAll: () => void;
    }

    /** `cc.director.getRunningScene()`：截图前 `visit()` 用。 */
    interface Director {
        getRunningScene(): cc.Scene;
    }

    /** 渲染访问方法，声明文件对 `Node` / `Scene` 的共同基类漏了 `visit`。 */
    interface _BaseNode {
        visit(): void;
    }

    namespace sys {
        /** 当前操作系统名，与下面这些常量比较。 */
        let os: string;
        let OS_IOS: string;
        let OS_ANDROID: string;
        let OS_WINDOWS: string;
        let isNative: boolean;
        /** 本地存储：浏览器为 localStorage，原生环境为 jsb 实现。 */
        let localStorage: LocalStorageLike;
        function openURL(url: string): void;
    }

    /** `cc.url.raw`：把 `resources/` 相对路径转成可用 URL。 */
    namespace url {
        function raw(url: string): string;
    }

    /** 客户端版本号：`AppStart` 从 `resources/ver/cv.txt` 读入后赋值。 */
    let VERSION: string;

    /** `creator.d.ts` 里 `cc.log` 只声明了两个形参，引擎实际支持任意追加参数。 */
    export function log(obj: unknown, ...subst: unknown[]): void;
}

/** `cc.sys.localStorage` 本项目实际用到的方法。 */
interface LocalStorageLike {
    getItem(key: string): string | null;
    setItem(key: string, value: string | number): void;
    removeItem(key: string): void;
}

// ---------------------------------------------------------------------------
// 组件与资源
// ---------------------------------------------------------------------------

declare namespace cc {
    /**
     * `creator.d.ts` 里完全没有 `Slider` 的声明，而 `Utils.addSlideEvent` 要
     * `node.getComponent(cc.Slider)`、`Settings` 面板要读写 `progress`。
     * 只补本项目实际用到的成员。
     */
    interface Slider extends Component {
        /** 滑动事件回调列表（`Utils.addSlideEvent` 往这里 push）。 */
        slideEvents: Component.EventHandler[];
        /** 当前进度值（`Settings` 面板读写它）。 */
        progress: number;
    }
    /** `getComponent(cc.Slider)` 要一个构造器值；`prototype` 同时满足按构造器取组件的重载。 */
    var Slider: { new (): Slider; prototype: Slider };

    /** `cc.Size` 只声明了构造参数，漏了实例上的 `width` / `height`（`BGScaler` / `Utils` 直接读）。 */
    interface Size {
        width: number;
        height: number;
    }

    /** 截图用的渲染纹理（`AnysdkMgr.shareResult` 使用），`creator.d.ts` 里完全没有。 */
    interface RenderTexture {
        setPosition(position: cc.Vec2): void;
        begin(): void;
        end(): void;
        saveToFile(fileName: string, format?: number): void;
    }
    var RenderTexture: { new (width: number, height: number): RenderTexture };

    /** `saveToFile` 的图片格式常量。 */
    var IMAGE_FORMAT_JPG: number;
}

// ---------------------------------------------------------------------------
// cc._decorator：creator.d.ts 完全没有声明（Creator 2.4 的 ES6 class 装饰器 API）
// ---------------------------------------------------------------------------

declare namespace cc {
    /** `@property` 接受的属性描述符；这里只列本项目实际用到的成员。 */
    interface PropertyOptions {
        /** 属性的类型构造器（可以是 `[cc.Label]` 这种数组形式）。 */
        type?: unknown;
        /** 初值；本项目一律用字段初始化器写初值，所以描述符里不带它。 */
        default?: unknown;
        visible?: boolean | (() => boolean);
        displayName?: string;
        tooltip?: string;
        multiline?: boolean;
        readonly?: boolean;
        serializable?: boolean;
        editorOnly?: boolean;
        override?: boolean;
        animatable?: boolean;
        formerlySerializedAs?: string;
        min?: number;
        max?: number;
        step?: number;
        range?: number[];
        slide?: boolean;
    }

    /**
     * `cc._decorator`：Creator 2.4 用它声明 ES6 class 组件。
     *
     * 这套装饰器最终仍走引擎的 `cc.Class`（见引擎 `CCClassDecorator.js`：`@ccclass` 内部调用
     * `cc.Class(proto)` 并带 `__ES6__: true`），所以类名、uuid 注册、`properties` 元数据都与老的
     * `cc.Class({...})` 写法完全一致。
     *
     * 注意两点：
     *  - `@ccclass` **不要传名字**：项目组件的类名由引擎取脚本名（`_RF.push` 的第 3 个参数），
     *    传名字反而会触发引擎告警；
     *  - 不带参数的 `@property foo = 0`（直接当装饰器用）与 `@property(cc.Label) foo = null`
     *    （工厂写法）是两种调用形态，引擎两种都支持，这里用两个重载分别声明。
     */
    namespace _decorator {
        function ccclass(target: Function): void;
        function ccclass(name: string): (target: Function) => void;
        function property(
            target: object,
            propertyKey: string | symbol,
            descriptor?: PropertyDescriptor,
        ): void;
        function property(
            options?: PropertyOptions | Function | [Function] | number | string | boolean | null,
        ): (target: object, propertyKey: string | symbol) => void;
    }
}

// ---------------------------------------------------------------------------
// 全局对象
// ---------------------------------------------------------------------------

/** `HTTP.js` 自己挂在 xhr 上的重试标记（`creator.d.ts` 与 lib.dom 都没有它）。 */
interface XMLHttpRequest {
    hasRetried: boolean;
    /** 老代码按 Creator 老 API 给 `setRequestHeader` 传了第 3 个参数（字符集），DOM 声明只有两个。 */
    setRequestHeader(header: string, value: string, charset: string): void;
}

/**
 * `Login.ts` 与 `History.ts` 都调用 `String.prototype.format`（`Login.ts` 顶部把它挂到原型上，
 * 老代码如此）。这里只补声明：`this` 收窄成 string，其余参数不收窄（老代码既传对象也传一串数字）。
 */
interface String {
    format(this: string, ...args: unknown[]): string;
}

/** Node/JSB 宿主提供的 `Buffer`（`creator.d.ts` 与 `lib.dom` 都没有声明），只补这里用到的成员。 */
declare class Buffer {
    constructor(str: string, encoding: string);
    toString(encoding?: string): string;
}

/** 原生桥 `jsb` 的最小声明：本项目只用到反射调用与文件工具。 */
declare namespace jsb {
    namespace reflection {
        /** 调用原生静态方法；参数与返回值都由原生侧约定，统一按 `unknown` 收口。 */
        var callStaticMethod: (...args: unknown[]) => unknown;
    }
    namespace fileUtils {
        function getWritablePath(): string;
        function getDataFromFile(path: string): Uint8Array;
        function writeDataToFile(data: Uint8Array, path: string): void;
        function isFileExist(path: string): boolean;
        function removeFile(path: string): void;
        function isDirectoryExist(path: string): boolean;
        function createDirectory(path: string): void;
    }
}

// ---------------------------------------------------------------------------
// 运行期动态挂在节点 / 组件上的字段（不是 Creator 的序列化属性）
// ---------------------------------------------------------------------------

declare namespace cc {
    interface Node {
        /**
         * `MJGame.initDragStuffs` 在 TOUCH_START 时把该节点上 `cc.Button` 的 `interactable`
         * 抄一份存到节点上，后面的 TOUCH_MOVE / TOUCH_END / TOUCH_CANCEL 再读它。
         */
        interactable: boolean;
    }

    interface Component {
        /**
         * `MJGame.initDragStuffs` 的 TOUCH_MOVE 回调里，老代码读的是**组件实例**上的
         * `this.width` / `this.height`（TOUCH_START 里读的才是 `this.node.width`）。
         * 这里只是让原写法通过类型检查，取值方式与迁移前完全一致。
         */
        width: number;
        height: number;
    }
}
