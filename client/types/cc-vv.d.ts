/**
 * `cc.vv` 单例的全局类型声明（只服务类型检查，不产生运行时代码）。
 *
 * `AppStart.initMgr()` 里 `cc.vv = {}` 是个**裸对象字面量**，逐个挂上下面这些成员；
 * 本文件把这条隐式契约显式化。几个容易踩的点：
 *
 *  - `cc.vv.net` / `cc.vv.global` **不是实例**，而是 `require(...)` 得到的 cc.Class 构造函数本身
 *    （字段都在 `statics` 里），所以类型直接写成「带这些成员的类对象」，**不要 `new` 它们**
 *    （`new` 出来的实例会与原类共享 statics 里的 handlers/sio）。
 *  - `cc.vv.http` 是 `HTTP.js` 的 CommonJS exports 对象。
 *  - 组件在自己 `onLoad` 里挂上来的单例（`alert` / `wc` / `chat` / `popupMgr` / `userinfoShow` /
 *    `radiogroupmgr` / `mahjongmgr`）可能还没加载，声明里保留可空，调用点沿用原有的判空写法。
 */

/** `HTTP.js` 的 exports：`cc.vv.http`。 */
interface HttpModule {
    /** 账号服地址，硬编码在 HTTP.js 第 2 行。 */
    master_url: string;
    /** 当前使用的地址，切换大厅服/游戏服时被外部改写。 */
    url: string;
    /** 登录令牌，`sendRequest` 会自动拼进 data。 */
    token: string | null;
    sendRequest(
        path: string,
        data: { [key: string]: unknown } | null,
        handler?: ((ret: HttpResp) => void) | null,
        extraUrl?: string | null,
    ): XMLHttpRequest;
    setURL(url: string): void;
}

/** `Global.js`：`cc.vv.global` 是类本身，字段全在 statics 上。 */
interface GlobalClass {
    isstarted: boolean;
    netinited: boolean;
    userguid: number;
    nickname: string;
    money: number;
    lv: number;
    roomId: number;
}

/** 网络事件处理器：`Net.addHandler` 注册的回调，data 已经过 JSON.parse（字符串载荷）。 */
type NetHandler = (data: unknown) => void;

/** `Net.js`：`cc.vv.net` 是类本身，成员全在 statics 上，**不要 new**。 */
interface NetClass {
    /** 游戏服地址，由 `GameNetMgr.connectGameServer` 写入 `ip:port`。 */
    ip: string;
    sio: SocketIOSocket | null;
    isPinging: boolean;
    fnDisconnect: (() => void) | null;
    handlers: { [event: string]: NetHandler };
    /** 心跳延迟；并未在 statics 里声明，是运行时动态字段，`Status.js` 读它。 */
    delayMS?: number | null;
    lastSendTime?: number;
    lastRecieveTime?: number;
    addHandler(event: string, fn: NetHandler): void;
    connect(fnConnect: (data: unknown) => void, fnError: () => void): void;
    /** 拼写就是 Hearbeat，不要改。 */
    startHearbeat(): void;
    send(event: string, data?: unknown): void;
    ping(): void;
    close(): void;
    /** 回调参数是 boolean（`ret.errcode == 0`），不是整个响应。 */
    test(fnResult: (ok: boolean) => void): void;
}

/** `UserMgr.js` 实例：`cc.vv.userMgr`。 */
interface UserMgr {
    account: string | number | null;
    /** 注意是小写 d 的 userId，与座位里的 `userid` 大小写不同。 */
    userId: number | null;
    userName: string | null;
    lv: number;
    exp: number;
    coins: number;
    gems: number;
    /** 鉴权串（md5），历史原因字段默认值是数字 0。 */
    sign: string | number | null;
    ip: string;
    sex: number;
    /** 还在房间里的房号。 */
    roomData: string | null;
    /** 断线时暂存的房号。 */
    oldRoomId: string | null;
    /** 公告，`Hall.js` 首次使用时动态创建。 */
    notice?: { version: unknown; msg: string } | null;
    /** 宝石提示，同上。 */
    gemstip?: { version: unknown; msg: string } | null;
    guestAuth(): void;
    onAuth(ret: HttpResp): void;
    login(): void;
    create(name: string): void;
    enterRoom(roomId: string | number | null, callback?: (ret: HttpResp) => void): void;
    /** 回调拿到的是 `ret.history`，不是整个响应。 */
    getHistoryList(callback: (history: unknown) => void): void;
    getGamesOfRoom(uuid: string, callback: (data: unknown) => void): void;
    getDetailOfGame(uuid: string, index: number, callback: (data: unknown) => void): void;
}

/** `ReplayMgr.js` 实例：`cc.vv.replayMgr`。 */
interface ReplayMgr {
    _lastAction: ReplayAction | null;
    _actionRecords: number[] | null;
    _currentIndex: number;
    clear(): void;
    init(data: ReplayDetail): void;
    isReplay(): boolean;
    getNextAction(): ReplayAction | null;
    /** 返回值被当作「下一次动作的延时秒数」，-1 表示没有更多动作。 */
    takeAction(): number;
}

/** `MahjongMgr.js` 实例：`cc.vv.mahjongmgr`（**全小写**）。 */
interface MahjongMgr {
    leftAtlas: cc.SpriteAtlas;
    rightAtlas: cc.SpriteAtlas;
    bottomAtlas: cc.SpriteAtlas;
    bottomFoldAtlas: cc.SpriteAtlas;
    emptyAtlas: cc.SpriteAtlas;
    pengPrefabSelf: cc.Prefab;
    pengPrefabLeft: cc.Prefab;
    holdsEmpty: cc.SpriteFrame[];
    _sides: string[] | null;
    _pres: string[] | null;
    _foldPres: string[] | null;
    getMahjongSpriteByID(id: Pai): string;
    /** 0 筒 / 1 条 / 2 万；越界返回 undefined。 */
    getMahjongType(id: Pai): number | undefined;
    getSpriteFrameByMJID(pre: string, mjid: Pai): cc.SpriteFrame;
    getAudioURLByMJID(id: Pai): string;
    getEmptySpriteFrame(side: string): cc.SpriteFrame;
    /** "myself" 时返回 null。 */
    getHoldsEmptySpriteFrame(side: string): cc.SpriteFrame | null;
    /** 原地排序，按定缺把该花色排到尾部（会改动传入数组）。 */
    sortMJ(mahjongs: PaiList, dingque: number): void;
    getSide(localIndex: number): string;
    getPre(localIndex: number): string;
    getFoldPre(localIndex: number): string;
}

/** `AudioMgr.js` 实例：`cc.vv.audioMgr`。 */
interface AudioMgr {
    bgmVolume: number;
    sfxVolume: number;
    bgmAudioID: number;
    init(): void;
    getUrl(url: string): string;
    playBGM(url: string): void;
    playSFX(url: string): void;
    setSFXVolume(v: number): void;
    setBGMVolume(v: number, force?: boolean): void;
    pauseAll(): void;
    resumeAll(): void;
}

/** `VoiceMgr.js` 实例：`cc.vv.voiceMgr`；所有方法在非 native 环境是安全的 no-op。 */
interface VoiceMgr {
    onPlayCallback: (() => void) | null;
    _voiceMediaPath: string | null;
    init(): void;
    prepare(filename: string): void;
    release(): void;
    cancel(): void;
    writeVoice(filename: string, voiceData: unknown): void;
    clearCache(filename: string): void;
    play(filename: string): void;
    stop(): void;
    getVoiceLevel(maxLevel: number): number;
    getVoiceData(filename: string): string;
    download(): void;
    setStorageDir(dir: string): void;
}

/** `AnysdkMgr.js` 实例：`cc.vv.anysdkMgr`。 */
interface AnysdkMgr {
    _isCapturing: boolean;
    /** 由 `init()` 动态写入。 */
    ANDROID_API?: string;
    IOS_API?: string;
    init(): void;
    /** 0~1 的电量比例；非 native 环境返回 0.9。 */
    getBatteryPercent(): number;
    login(): void;
    share(title: string, desc: string): void;
    shareResult(): void;
    onLoginResp(code: unknown): void;
}

/** `Utils.js` 实例：`cc.vv.utils`。 */
interface Utils {
    /** 第 3、4 参是组件名与方法名的**字符串**（Creator EventHandler 语义），不是函数。 */
    addClickEvent(node: cc.Node, target: cc.Node, component: string, handler: string): void;
    addSlideEvent(node: cc.Node, target: cc.Node, component: string, handler: string): void;
    addEscEvent(node: cc.Node): void;
    /** 拼写就是 Sreen，不要改名。 */
    setFitSreenMode(): void;
}

/** `GameNetMgr.js` 实例：`cc.vv.gameNetMgr`，对局状态机。 */
interface GameNetMgr {
    /** 组件把 `this.node` 挂上来，`dispatchEvent` 用它 emit 本地事件。 */
    dataEventHandler: cc.Node | null;
    roomId: string | null;
    maxNumOfGames: number;
    numOfGames: number;
    /** 剩余牌数。 */
    numOfMJ: number;
    /** 自己的座位号；-1 = 未知。 */
    seatIndex: number;
    seats: SeatData[] | null;
    turn: number;
    /** 庄家座位；-1 = 未开始。 */
    button: number;
    /** 自己的定缺；-1 = 未定。 */
    dingque: number;
    /** 最近打出的牌；-1 = 无。 */
    chupai: number;
    /** "" | "begin" | "playing" | "dingque" | "huanpai"（直接透传服务端 game.state）。 */
    gamestate: string;
    isDingQueing: boolean;
    isHuanSanZhang: boolean;
    isOver: boolean;
    /** 房间配置；`properties` 里没有它，是在 `login_result` / `prepareReplay` 里动态挂上的。 */
    conf: GameConf | null | undefined;
    /** 0 对家 / 1 下家 / 2 上家；-1 = 未知（注意全小写）。 */
    huanpaimethod?: number;
    curaction?: ActionPushData | null;
    /** 拼写就是 dissove（服务端字段名如此）。 */
    dissoveData: DissolveNoticePush | null;

    reset(): void;
    clear(): void;
    dispatchEvent(event: string, data?: unknown): void;
    /** 找不到返回 -1。 */
    getSeatIndexByID(userId: number): number;
    isOwner(): boolean;
    /** 座位不存在时运行时会返回 undefined（老代码不判空，这里不改变既有行为）。 */
    getSeatByID(userId: number): SeatData;
    getSelfData(): SeatData;
    getLocalIndex(index: number): number;
    prepareReplay(roomInfo: HistoryRoomInfo, detailOfGame: ReplayDetail): void;
    /** 配置不完整时返回空串。 */
    getWanfa(): string;
    initHandlers(): void;
    connectGameServer(data: HttpResp): void;

    // 以下动作方法同时被 ReplayMgr 当作「本地重放 API」复用。
    doGuo(seatIndex: number, pai: Pai): void;
    doMopai(seatIndex: number, pai: Pai): void;
    doChupai(seatIndex: number, pai: Pai): void;
    doPeng(seatIndex: number, pai: Pai): void;
    doGang(seatIndex: number, pai: Pai, gangtype?: string): void;
    doHu(data: HuPush): void;
    doTurnChange(si: number): void;
    getGangType(seatData: SeatData, pai: Pai): string;
}

/** 各管理器的构造器类型，供 `require(...)` 的断言使用。 */
interface UserMgrConstructor { new (): UserMgr; }
interface ReplayMgrConstructor { new (): ReplayMgr; }
interface GameNetMgrConstructor { new (): GameNetMgr; }
interface AnysdkMgrConstructor { new (): AnysdkMgr; }
interface VoiceMgrConstructor { new (): VoiceMgr; }
interface AudioMgrConstructor { new (): AudioMgr; }
interface UtilsConstructor { new (): Utils; }

/** `WaitingConnection.js` 挂到 `cc.vv.wc`。 */
interface LoadingIndicator {
    show(msg: string): void;
    hide(): void;
}

/** `Alert.js` 挂到 `cc.vv.alert`（销毁时会置回 null）。 */
interface AlertBox {
    /** 第 4 参是「是否显示取消按钮」，`Utils.addEscEvent` 会传 `true`。 */
    show(title: string, msg: string, callback?: () => void, needcancel?: boolean): void;
}

/** `Chat.js` 挂到 `cc.vv.chat`。 */
interface ChatApi {
    getQuickChatInfo(index: number): QuickChatInfo;
}

/** `PopupMgr.js` 挂到 `cc.vv.popupMgr`。 */
interface PopupMgrApi {
    showSettings(): void;
}

/** `UserInfoShow.js` 挂到 `cc.vv.userinfoShow`。 */
interface UserInfoShowApi {
    show(name: string, userId: number, icon: cc.Sprite, sex: number, ip: string): void;
}

/** `RadioGroupMgr.js`：`RadioButton.js` 首次用到时懒创建，挂在 `cc.vv.radiogroupmgr`。 */
interface RadioGroupMgrApi {
    init(): void;
    check(btn: cc.Node): void;
    add(btn: cc.Node): void;
    del(btn: cc.Node): void;
}

/** `AppStart.initMgr()` 组装出来的全局单例容器。 */
interface CCVV {
    userMgr: UserMgr;
    replayMgr: ReplayMgr;
    http: HttpModule;
    global: GlobalClass;
    net: NetClass;
    gameNetMgr: GameNetMgr;
    anysdkMgr: AnysdkMgr;
    voiceMgr: VoiceMgr;
    audioMgr: AudioMgr;
    utils: Utils;
    /** 服务器信息，`AppStart` 拿到 `/get_serverinfo` 后写入。 */
    SI: ServerInfo;

    // 由组件在自己的 onLoad 里挂上来；只有 alert 会在销毁时被置回 null，其余全客户端没有置空点。
    mahjongmgr: MahjongMgr;
    wc: LoadingIndicator;
    alert: AlertBox | null;
    chat: ChatApi;
    popupMgr: PopupMgrApi;
    userinfoShow: UserInfoShowApi;
    /** 懒创建：RadioButton.js 里首次用到且为空时才 new。 */
    radiogroupmgr: RadioGroupMgrApi | null;
    /** 头像缓存（ImageLoader.js）。 */
    images: { [url: string]: cc.SpriteFrame } | null;
    /** 用户简要资料缓存（ImageLoader.js）。 */
    baseInfoMap: { [userid: string]: UserBaseInfo } | null;
}

declare namespace cc {
    /** 全局单例容器；由 `AppStart.initMgr()` 在启动时装配。 */
    let vv: CCVV;
    /** 启动参数（`AppStart.urlParse()` 解析 location 查询串得到）。 */
    let args: { [key: string]: string };
}
