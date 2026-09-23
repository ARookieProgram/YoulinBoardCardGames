/**
 * 游戏域模型：房间 / 座位 / 单局对局状态。
 *
 * 这些结构在 `roommgr`、`gamemgr_xlch`、`gamemgr_xzdd` 之间共享。迁移到 TypeScript 之前
 * 它们都是"用到哪写到哪"的动态对象，这里的字段是照着代码里真实出现过、并带上了真实取值
 * 类型整理出来的，语义以两份 gamemgr 的实现为准（两份实现的数据模型完全相同）。
 *
 * 命名对应关系：
 *   - `RoomInfo`  房间（`roommgr.rooms[roomId]`）
 *   - `RoomSeat`  房间里的座位（`roomInfo.seats[i]`），管的是玩家与分数
 *   - `GameState` 一局对局（gamemgr 里的 `game`）
 *   - `GameSeat`  对局里的座位（`game.gameSeats[i]`），管的是手牌与操作
 */

/** 玩法类型，决定 `roommgr` 用哪份 gamemgr 实现。 */
export type RoomType = "xlch" | "xzdd";

/** `game.state` 的全部取值（来源于两份 gamemgr 里的赋值与比较）。 */
export type GamePhase = "idle" | "huanpai" | "dingque" | "playing" | "nop";

/** 落库的房间配置（`t_rooms.base_info`，对局逻辑只认这一层）。 */
export interface RoomConf {
  type: RoomType;
  baseScore: number;
  zimo: number;
  jiangdui: number;
  /** 换三张开关，由入参 `huansanzhang` 映射而来。 */
  hsz: number;
  dianganghua: number;
  menqing: number;
  tiandihu: number;
  maxFan: number;
  maxGames: number;
  /** 房主 userId。 */
  creator: number;
}

/** 建房入参（`createRoom` 校验的那一层，来自客户端 `CreateRoom.js`）。 */
export interface RoomCreateConf {
  type: string;
  difen: number;
  zimo: number;
  jiangdui: number;
  huansanzhang: number;
  zuidafanshu: number;
  jushuxuanze: number;
  dianganghua: string | number;
  menqing: number;
  tiandihu: number;
}

/** 听牌表里的一条：牌型与番数。 */
export interface TingPaiInfo {
  pattern: string;
  fan: number;
}

/** `findMaxFanTingPai` 的返回值：番数最大的那张听牌。 */
export interface MaxFanTingPai extends TingPaiInfo {
  pai: number;
}

/** 听牌表：牌 id -> 该牌的和牌信息。 */
export type TingMap = Record<number, TingPaiInfo | undefined>;

/** 手牌计数表：牌 id -> 张数（空间换时间，用于快速判定碰/杠）。 */
export type CountMap = Record<number, number>;

/** 胡牌记录（`GameSeat.huInfo` 的元素，字段按 gamemgr 里实际写入的形状整理）。 */
export interface HuInfoItem {
  /** 和牌类型；`hu` 里先写成 null，随后按分支赋值（"zimo"/"hu"/"ganghua"/"qiangganghu"…）。 */
  action: string | null;
  ishupai?: boolean;
  fan?: number;
  /** 牌型；`hu` 里先写成 null，随后由 tingMap 补上（"normal"/"duidui"/"7pairs"…）。 */
  pattern?: string | null;
  pai?: number;
  numofgen?: number;
  /** 被查大叫 / 点炮的目标座位。 */
  target?: number;
  /** 指回目标座位上 hanInfo 的下标。 */
  index?: number;
  /** 杠上花（`huData.isGangHu`）。 */
  isGangHu?: boolean;
  /** 抢杠胡（`huData.isQiangGangHu`）。 */
  isQiangGangHu?: boolean;
  /** 是否自摸（`huData.iszimo`）。 */
  iszimo?: boolean;
  /** 海底胡（`huData.isHaiDiHu`）。 */
  isHaiDiHu?: boolean;
  /** 天胡（`huData.isTianHu`，需要房间开 `tiandihu`）。 */
  isTianHu?: boolean;
  /** 地胡（`huData.isDiHu`，需要房间开 `tiandihu`）。 */
  isDiHu?: boolean;
}

/** 结算用的单条操作记录（`recordUserAction` 写入 `GameSeat.actions`）。 */
export interface UserActionRecord {
  /** 操作类型，实际写入的是字符串："angang" / "diangang" / "wangang" / "fanggang" / "zhuanshougang" / "maozhuanyu"。 */
  type: string;
  /** 受影响的座位；`maozhuanyu`（呼叫转移）那条记录是在 `hu` 里直接构造的，没有这个字段。 */
  targets?: number[];
  /** 结算时可能被标记为 "nop"（不结算）。 */
  state?: string;
  /** 这条杠的底分倍数，结算时读。 */
  score?: number;
  /** `maozhuanyu` 记录：被转移的那一家的座位。 */
  owner?: GameSeat | null;
  /** `maozhuanyu` 记录：指向被转移的那条杠记录。 */
  ref?: UserActionRecord | null;
  /** `maozhuanyu` 记录：被转移的杠钱已经扣过几次。 */
  payTimes?: number;
  /**
   * 是否自摸（xzdd 专属：`hu` 里往 `recordUserAction` 的返回值上写 `ac.iszimo`，
   * `calculateResult` 里按它决定收钱方式）。xlch 不写这个字段。
   */
  iszimo?: boolean;
}

/** 抢杠上下文（`game.qiangGangContext`）。 */
export interface QiangGangContext {
  turnSeat: GameSeat;
  seatData: GameSeat;
  pai: number;
  isValid: boolean;
}

/** 解散申请（`roomInfo.dr`，由 `dissolveRequest` 写入、`update()` 每秒检查超时）。 */
export interface DissolveRequest {
  /** 毫秒时间戳，超过它就算解散失败。 */
  endTime: number;
  /** 四个座位的同意状态。 */
  states: boolean[];
}

/** 房间里的一个座位：玩家身份、分数与该玩家的累计统计。 */
export interface RoomSeat {
  userId: number;
  score: number;
  name: string;
  ready: boolean;
  seatIndex: number;
  numZiMo: number;
  numJiePao: number;
  numDianPao: number;
  numAnGang: number;
  numMingGang: number;
  numChaJiao: number;
  /** 登录握手时由 `socket_service` 写入（`socket.handshake.address`）。 */
  ip?: string;
}

/** 房间。 */
export interface RoomInfo {
  /** `t_rooms.uuid`，建房前为空字符串。 */
  uuid: string;
  /** 6 位房间号。 */
  id: string;
  numOfGames: number;
  /** 秒级时间戳。 */
  createTime: number;
  nextButton: number;
  seats: RoomSeat[];
  conf: RoomConf;
  /** 玩法实现（`gamemgr_xlch` / `gamemgr_xzdd`），按 `conf.type` 懒加载。 */
  gameMgr: GameManager;
  /** 解散申请，仅在解散流程中被写入。 */
  dr?: DissolveRequest | null;
}

/** 一局对局。 */
export interface GameState {
  conf: RoomConf;
  roomInfo: RoomInfo;
  gameIndex: number;
  button: number;
  /** 洗好的牌墙，108 张。 */
  mahjongs: number[];
  currentIndex: number;
  gameSeats: GameSeat[];
  numOfQue: number;
  turn: number;
  /** 最近打出的牌。 */
  chuPai: number;
  state: GamePhase;
  /** 第一张胡的牌（-1 表示无）。 */
  firstHupai: number;
  yipaoduoxiang: number;
  fangpaoshumu: number;
  /** 操作流水，按 `si, action, pai` 依次 push，故为扁平数组。 */
  actionList: number[];
  /**
   * 胡牌顺序（xzdd 专属）：`hu` 里 push 座位号，结算时用 `indexOf` 得出 `huorder`。
   */
  hupaiList: number[];
  chupaiCnt: number;
  lastHuPaiSeat: number;
  qiangGangContext: QiangGangContext | null;
  /** 换三张用的换牌方式（0 对家 / 1 下家 / 2 上家），`huanSanZhang` 里写入后不再被读。 */
  huanpaiMethod?: number;
  /** 一局的基础信息 JSON，`construct_game_base_info` 写入、`store_game` 落库。 */
  baseInfoJson: string;
  /**
   * `hu` 里读过的字段，但**全仓库没有任何地方写入它**（只有 `GameSeat.lastFangGangSeat` 会被写）：
   * 运行结果是 `undefined`，`(undefined - n + 4) % 4` 得到 NaN。保留这个字段只为如实描述原实现，
   * 不要补初值（补了会改行为）。
   */
  lastFangGangSeat?: number;
}

/** 对局里的一个座位：手牌、副露、可执行操作与统计。 */
export interface GameSeat {
  game: GameState;
  seatIndex: number;
  userId: number;
  /** 手牌。 */
  holds: number[];
  /** 打出的牌。 */
  folds: number[];
  /** 暗杠的牌。 */
  angangs: number[];
  /** 点杠的牌。 */
  diangangs: number[];
  /** 弯杠（碰后补杠）的牌。 */
  wangangs: number[];
  /** 碰了的牌。 */
  pengs: number[];
  /** 定缺花色，-1 表示未定。 */
  que: number;
  /** 换三张换来的牌，未换时为 null。 */
  huanpais: number[] | null;
  countMap: CountMap;
  tingMap: TingMap;
  pattern: string;
  canGang: boolean;
  /** 可以杠的牌。 */
  gangPai: number[];
  canPeng: boolean;
  canHu: boolean;
  canChuPai: boolean;
  /** >=0 表示处于过胡状态：只能胡大于该番数的牌。 */
  guoHuFan: number;
  hued: boolean;
  actions: UserActionRecord[];
  iszimo: boolean;
  isGangHu: boolean;
  fan: number;
  score: number;
  huInfo: HuInfoElement[];
  lastFangGangSeat: number;
  numZiMo: number;
  numJiePao: number;
  numDianPao: number;
  numAnGang: number;
  numMingGang: number;
  numChaJiao: number;
  /** 结算时算出来的清一色标记（`calculateResult` 写入）。 */
  qingyise?: boolean;
  /** 结算时算出来的门清标记（房间开 `menqing` 时才写）。 */
  isMenQing?: boolean;
  /** 结算时算出来的金钩胡标记（手上只剩 1~2 张）。 */
  isJinGouHu?: boolean;
  /** 结算时算出来的中张标记（房间开 `menqing` 时才写）。 */
  isZhongZhang?: boolean;
  /**
   * 结算时算出来的根数：杠 + 碰后手里还有 1 张的 + 手里 4 张的。
   * xzdd 独有（xlch 用局部函数 `getNumOfGen`，不往座位上写）。
   */
  numofgen: number;
  /** 杠上炮胡标记（xzdd 独有，`hu` 里写）。 */
  isQiangGangHu: boolean;
  /** 海底胡标记（xzdd 独有，`hu` 里写）。 */
  isHaiDiHu: boolean;
  /** 天胡标记（xzdd 独有，房间开 `tiandihu` 时才可能写）。 */
  isTianHu: boolean;
  /** 地胡标记（xzdd 独有，房间开 `tiandihu` 时才可能写）。 */
  isDiHu: boolean;
}

/** `GameSeat.huInfo` 的元素别名（保持与历史字段名一致）。 */
export type HuInfoElement = HuInfoItem;

/**
 * 两份玩法实现共同满足的契约。
 *
 * `roommgr` 按房间类型懒加载其中一份（不能同时加载：两个模块在文件末尾都
 * `setInterval(update,1000)`，同时加载会跑起两个定时器），因此这里用接口把
 * "gamemgr 必须提供什么"固定下来，两份实现在各自文件末尾做一次编译期自检。
 */
export interface GameManager {
  setReady(userId: number, callback?: (errcode: number) => void): void;
  begin(roomId: string): void;
  huanSanZhang(userId: number, p1: number, p2: number, p3: number): void;
  /** `type` 是缺门花色：0 筒 / 1 条 / 2 万。 */
  dingQue(userId: number, type: number): void;
  chuPai(userId: number, pai: number): void;
  peng(userId: number): void;
  isPlaying(userId: number): boolean;
  gang(userId: number, pai: number): void;
  hu(userId: number): void;
  guo(userId: number): void;
  hasBegan(roomId: string): boolean;
  doDissolve(roomId: string): void;
  dissolveRequest(roomId: string, userId: number): RoomInfo | null;
  dissolveAgree(roomId: string, userId: number, agree: boolean): RoomInfo | null;
}
