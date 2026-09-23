/**
 * 客户端域模型：网络载荷、座位、房间配置、回放动作等结构。
 *
 * 这些类型是客户端「读服务端数据」的唯一收口，字段名严格按客户端代码里**实际使用**的写法定义
 * ——服务端的 `server/types/domain.ts` 命名与客户端并不完全一致（例如客户端是 `userid` /
 * `seatindex`，服务端是 `userId` / `seatIndex`），不要照抄服务端。
 *
 * 这些类型同样是网络边界的断言目标：`Net.js` 把字符串载荷 `JSON.parse` 后交给业务回调，
 * 回调里第一件事就是把它断言成本文件里的某个类型（见各 `addHandler` 的写法）。
 */

/** 一张牌：0-8 筒 / 9-17 条 / 18-26 万。 */
type Pai = number;
/** 一组牌。 */
type PaiList = number[];

/** 服务端 HTTP 接口的统一响应体（`HTTP.js` 的 handler 收到的东西）。 */
interface HttpResp {
    errcode: number;
    /** 失败时的错误描述；JSON 解析失败的分支里塞进来的是一个 Error 对象。 */
    errmsg?: unknown;
    // 以下字段来自 `/guest`、`/login`、`/create`、`/enter_private_room` 等接口，按真实返回声明。
    account?: string;
    sign?: string | number;
    userid?: number;
    name?: string;
    lv?: number;
    exp?: number;
    coins?: number;
    gems?: number;
    sex?: number;
    ip?: string;
    port?: string;
    token?: string;
    roomid?: string;
    time?: number;
    history?: unknown;
    data?: unknown;
    // `/get_serverinfo`（账号服）返回的服务器信息，客户端整体塞进 `cc.vv.SI`。
    hall?: string;
    appweb?: string;
    version?: string;
}

/** 账号服 `/get_serverinfo` 的返回体，整个对象挂在 `cc.vv.SI` 上。 */
interface ServerInfo {
    hall: string;
    appweb: string;
    version: string;
}

/** `cc.vv.baseInfoMap` 里缓存的用户简要资料（`/base_info` 返回）。 */
interface UserBaseInfo {
    name?: string;
    sex: number;
    url?: string | null;
}

/** 房间玩法配置：`cc.vv.gameNetMgr.conf`。服务端下发时字段齐全，`prepareReplay` 只造 `type`。 */
interface GameConf {
    /** 玩法分支："xlch"（血战到底）/ "xzdd"（血战到底·换三张）。 */
    type: string;
    /** 局数与封顶番数，`getWanfa` 用它们判断配置是否完整。 */
    maxGames?: number;
    maxFan?: number;
    /** 换三张开关（落库名是 hsz，不是 huansanzhang）。 */
    hsz?: number;
    /** 1 = 自摸加番，否则自摸加底。 */
    zimo?: number;
    jiangdui?: number;
    /** 1 = 点杠花(自摸)，否则点杠花(放炮)。 */
    dianganghua?: number;
    menqing?: number;
    tiandihu?: number;
}

/** 一条胡牌记录（`seat.huinfo` 的元素，结算面板也读它）。 */
interface HuInfoItem {
    /** 是否「本人胡」的记录；false 表示被别人胡/被查大叫。 */
    ishupai?: boolean;
    /** "hu" | "zimo" | "ganghua" | "dianganghua" | "gangpaohu" | "qiangganghu" |
     *  "chadajiao" | "fangpao" | "gangpao" | "beiqianggang" | "beichadajiao" | null。 */
    action?: string | null;
    /** 胡的那张牌；`hu()` 里初值 -1，流局/被查大叫路径真的会传 -1。 */
    pai?: Pai;
    fan?: number;
    /** "normal" | "duidui" | "7pairs" | "l7pairs" | "j7pairs" | "jiangdui" | null。 */
    pattern?: string | null;
    numofgen?: number;
    /** 放炮/被抢杠/被查大叫的目标座位号；`hu()` 里初值 -1。 */
    target?: number;
    /** 指回目标座位 huinfo 的下标。 */
    index?: number;
    /** 以下字段只有 xzdd 的 `hu()` 会写。 */
    isGangHu?: boolean;
    isQiangGangHu?: boolean;
    iszimo?: boolean;
    isHaiDiHu?: boolean;
    isTianHu?: boolean;
    isDiHu?: boolean;
}

/**
 * 一个座位在对局中的全部状态（`GameNetMgr.seats[i]`）。
 *
 * 初始来自 `login_result.data.seats[i]`，之后被 `game_sync_push` / `*_notify_push` /
 * `game_over_push` 逐步补字段，所以「刚登录还没开局」时后面的字段可能并不存在。
 * 数组字段按客户端既有习惯声明为「一定有数组」——老代码里对 null 的判断（`if (s.folds == null)`）
 * 保留原样，那是服务端数据不齐时的兜底。
 */
interface SeatData {
    /** 服务端座位号（小写 i）。 */
    seatindex: number;
    /** 玩家 id；0 = 空座位（`exit_notify_push` 会置 0）。 */
    userid: number;
    name: string;
    ip: string;
    online: boolean;
    ready: boolean;
    score: number | null;
    /** 手牌。 */
    holds: PaiList;
    /** 牌河。 */
    folds: PaiList;
    pengs: PaiList;
    angangs: PaiList;
    diangangs: PaiList;
    wangangs: PaiList;
    /** 定缺花色：0 筒 / 1 条 / 2 万；-1 = 未定。 */
    dingque: number;
    hued: boolean;
    iszimo?: boolean;
    /** 换三张选中的三张；未换为 null。 */
    huanpais: PaiList | null;
    huinfo?: HuInfoItem[] | null;
}

/** 回放里的一个动作记录（`ReplayMgr` 每 3 个数字组装成一条）。 */
interface ReplayAction {
    si: number;
    /** 1 = 摸牌 / 2 = 出牌 / 3 = 碰 / 4 = 杠 / 5 = 胡（与 GameNetMgr 的 do* 一一对应）。 */
    type: number;
    pai: Pai;
}

/** 快捷聊天/表情配置项（`Chat.js` 的 `_quickChatInfo`；字段名按运行期实际返回值）。 */
interface QuickChatInfo {
    index: number;
    sound?: string;
    /** 快捷语文本（`Chat.js` 存的就是这个字段）。 */
    content?: string;
}

/** `login_result` 推送：errcode 为 0 时才带 data。 */
interface LoginResultPush {
    errcode: number;
    errmsg: string;
    data?: {
        roomid: string;
        conf: GameConf;
        numofgames: number;
        seats: SeatData[];
    };
}

/** `game_sync_push` 里的单个座位（服务端 SyncSeat，`que` 即客户端的 `dingque`）。 */
interface SyncSeat {
    userid: number;
    /** 只有自己的座位会带手牌。 */
    holds?: PaiList;
    folds: PaiList;
    angangs: PaiList;
    diangangs: PaiList;
    wangangs: PaiList;
    pengs: PaiList;
    que: number;
    hued: boolean;
    huinfo: HuInfoItem[];
    iszimo: boolean;
    huanpais: PaiList | null;
}

/** `game_sync_push`。 */
interface GameSyncPush {
    state: string;
    numofmj: number;
    button: number;
    turn: number;
    /** 注意大写 P。 */
    chuPai: number;
    seats: SyncSeat[];
    huanpaimethod?: number;
}

/** `game_action_push`（无操作时服务端发 undefined）。 */
interface ActionPushData {
    pai: Pai;
    hu: boolean;
    peng: boolean;
    gang: boolean;
    gangpai: PaiList;
    /** 服务端在 `sendMsg` 之后才写，客户端实际收不到。 */
    si?: number;
}

/** `hu_push`（这里的座位字段是小写 `seatindex`）。 */
interface HuPush {
    seatindex: number;
    iszimo: boolean;
    /** 可能为 -1（流局/被查大叫路径）。 */
    hupai: Pai;
}

/** `game_chupai_notify_push` 与 `guo_notify_push`（这里的 userId 是大写 I）。 */
interface ChupaiNotifyPush {
    userId: number;
    pai: Pai;
}

/** `peng_notify_push`（这里又是小写 userid）。 */
interface PengNotifyPush {
    userid: number;
    pai: Pai;
}

/** `gang_notify_push`。 */
interface GangNotifyPush {
    userid: number;
    pai: Pai;
    /** "angang" | "diangang" | "wangang"。 */
    gangtype: string;
}

/** `user_state_push`。 */
interface UserStatePush {
    userid: number;
    online: boolean;
}

/** `user_ready_push`。 */
interface UserReadyPush {
    userid: number;
    ready: boolean;
}

/** `huanpai_notify` / `game_huanpai_over_push` 复用同一形状。 */
interface HuanPaiNotifyPush {
    /** 服务端填的其实是 userId，客户端却当座位下标用（既有行为，不要改）。 */
    si?: number;
    huanpais?: PaiList | null;
    /** 0 对家 / 1 下家 / 2 上家，只有 `game_huanpai_over_push` 有。 */
    method?: number;
}

/** `dissolve_notice_push`。 */
interface DissolveNoticePush {
    time: number;
    /** 4 个座位的同意状态。 */
    states: boolean[];
}

/** `game_over_push`。 */
interface GameOverPush {
    /** 空数组表示本局无人胡。 */
    results: GameResultSeat[];
    /** 只有最后一局非 null，非 null 时再派发 `game_end`。 */
    endinfo: EndInfo[] | null;
}

/** `game_over_push.results[i]`（服务端 UserResult；这里 userId 是大写 I）。 */
interface GameResultSeat {
    userId: number;
    actions: { type: string }[];
    pengs: PaiList;
    angangs: PaiList;
    diangangs: PaiList;
    wangangs: PaiList;
    /** GameOver 会原地 sort/pop/push，这是客户端本地副本。 */
    holds: PaiList;
    /** 本局得分。 */
    score: number;
    /** 累计得分，会写回 `seats[i].score`。 */
    totalscore: number;
    /** xlch 有，xzdd 无。 */
    huinfo?: HuInfoItem[];
    /** 以下 xlch 独有。 */
    qingyise?: boolean;
    menqing?: boolean;
    jingouhu?: boolean;
    /** 以下 xzdd 独有。 */
    numofgen?: number;
    fan?: number;
    pattern?: string;
    isganghu?: boolean;
    zhongzhang?: boolean;
    haidihu?: boolean;
    tianhu?: boolean;
    dihu?: boolean;
    /** 胡牌顺序下标，-1 = 未胡。 */
    huorder?: number;
}

/** `game_end` 的载荷。 */
interface EndInfo {
    numzimo: number;
    numjiepao: number;
    numdianpao: number;
    numangang: number;
    numminggang: number;
    numchadajiao: number;
}

/** `chat_push` / `quick_chat_push` / `emoji_push` / `voice_msg_push` 共用。 */
interface ChatPush {
    sender: number;
    /** chat 是字符串；quick_chat/emoji 是索引；voice_msg 是 JSON 字符串。 */
    content: string | number;
}

/** 语音消息内容（`voice_msg` 的 content 再 parse 一次得到）。 */
interface VoiceMsgContent {
    msg: string;
    time: number;
}

/** 登录握手（`connectGameServer` → `net.send("login", sd)`）。 */
interface LoginHandshake {
    token: string;
    roomid: string;
    time: number;
    sign: string;
}

/** 回放用的一局基础信息（`GameNetMgr.prepareReplay` 消费）。 */
interface BaseInfo {
    type: string;
    button: number;
    index: number;
    mahjongs: PaiList;
    /** 长度 4，`prepareReplay` 直接赋给 `seat.holds`。 */
    game_seats: PaiList[];
}

/** 战绩接口返回的房间对象（`History.js`）。 */
interface HistoryRoomInfo {
    /** 房间号（不是 roomId）。 */
    id: string;
    /** `get_games_of_room` 的入参。 */
    uuid: string;
    /** 秒级时间戳，客户端 *1000 后格式化。 */
    time: number;
    seats: SeatData[];
    base_info?: BaseInfo;
}

/** 单局战绩行（`get_games_of_room` 返回的 data[i]）。 */
interface GameRecord {
    create_time: number;
    /** JSON 字符串，parse 后是 4 个分数。 */
    result: string;
    base_info: BaseInfo | string;
}

/** `get_detail_of_game` 返回的一局详情。 */
interface ReplayDetail {
    base_info: BaseInfo;
    /** 动作序列，`ReplayMgr.init` 直接取 `.action_records`。 */
    action_records: number[];
}

/** `CreateRoom.js` 构造、`/create_private_room` 以 JSON 字符串放在 conf 字段里。 */
interface RoomCreateConf {
    type: string;
    /** 底分下标，服务端映射成 DI_FEN[1,2,5]。 */
    difen: number;
    zimo: number;
    /** 以下四个开关直接来自 `CheckBox.checked`，所以可能是 boolean 也可能是 0/1。 */
    jiangdui: number | boolean;
    /** 注意这里叫 huansanzhang，落库后叫 hsz。 */
    huansanzhang: number | boolean;
    zuidafanshu: number;
    jushuxuanze: number;
    dianganghua: string | number;
    menqing: number | boolean;
    tiandihu: number | boolean;
}
