// 对局状态机：座位、手牌、轮次、定缺、换三张、结算。
//
// 本文件用 ES6 class + @ccclass/@property 装饰器（Creator 2.4 的官方写法）：
// 运行时行为与迁移前的 GameNetMgr.js 完全一致，只补了类型标注与跨网络边界的断言。
// `addHandler` 的回调收到的是 `unknown`（Net.js 已对字符串载荷做过 JSON.parse），
// 每个回调第一句把它断言成 `types/domain.d.ts` 里的具体推送类型，这就是网络边界。

const { ccclass, property } = cc._decorator;

/**
 * 游戏服在"账号被封禁"时返回的业务码（`game_server/socket_service.ts` /
 * `socket_service.py` 的 `login_result{errcode:4}`）。1 参数非法、2 签名错误、
 * 3 token 过期，4 是新增的封禁。
 */
const ERR_ACCOUNT_BANNED = 4;

@ccclass
export default class GameNetMgr extends cc.Component {
    @property dataEventHandler: cc.Node | null = null;
    @property roomId: string | null = null;
    @property maxNumOfGames: number = 0;
    @property numOfGames: number = 0;
    @property numOfMJ: number = 0;
    @property seatIndex: number = -1;
    @property seats: SeatData[] | null = null;
    @property turn: number = -1;
    @property button: number = -1;
    @property dingque: number = -1;
    @property chupai: number = -1;
    @property isDingQueing: boolean = false;
    @property isHuanSanZhang: boolean = false;
    @property gamestate: string = "";
    @property isOver: boolean = false;
    @property dissoveData: DissolveNoticePush | null = null;

    // 以下字段老代码是运行时动态挂到实例上的，**不是 Creator 的序列化属性**。
    // 这里用 declare 只声明类型、不产生运行时代码：与「字段不存在」完全一致，没有补任何初始值。
    declare conf: GameConf | null | undefined;
    declare curaction: ActionPushData | null | undefined;
    declare huanpaimethod: number | undefined;

    reset() {
        this.turn = -1;
        this.chupai = -1,
        this.dingque = -1;
        this.button = -1;
        this.gamestate = "";
        this.dingque = -1;
        this.isDingQueing = false;
        this.isHuanSanZhang = false;
        this.curaction = null;
        for (var i = 0; i < this.seats!.length; ++i) {
            this.seats![i].holds = [];
            this.seats![i].folds = [];
            this.seats![i].pengs = [];
            this.seats![i].angangs = [];
            this.seats![i].diangangs = [];
            this.seats![i].wangangs = [];
            this.seats![i].dingque = -1;
            this.seats![i].ready = false;
            this.seats![i].hued = false;
            this.seats![i].huanpais = null;
            this.huanpaimethod = -1;
        }
    }

    clear() {
        this.dataEventHandler = null;
        if (this.isOver == null) {
            this.seats = null;
            this.roomId = null;
            this.maxNumOfGames = 0;
            this.numOfGames = 0;
        }
    }

    dispatchEvent(event: string, data?: unknown) {
        if (this.dataEventHandler) {
            this.dataEventHandler.emit(event, data);
        }
    }

    getSeatIndexByID(userId: number) {
        for (var i = 0; i < this.seats!.length; ++i) {
            var s = this.seats![i];
            if (s.userid == userId) {
                return i;
            }
        }
        return -1;
    }

    isOwner() {
        return this.seatIndex == 0;
    }

    getSeatByID(userId: number) {
        var seatIndex = this.getSeatIndexByID(userId);
        var seat = this.seats![seatIndex];
        return seat;
    }

    getSelfData() {
        return this.seats![this.seatIndex];
    }

    getLocalIndex(index: number) {
        var ret = (index - this.seatIndex + 4) % 4;
        return ret;
    }

    prepareReplay(roomInfo: HistoryRoomInfo, detailOfGame: ReplayDetail) {
        this.roomId = roomInfo.id;
        this.seats = roomInfo.seats;
        this.turn = detailOfGame.base_info.button;
        var baseInfo = detailOfGame.base_info;
        for (var i = 0; i < this.seats.length; ++i) {
            var s = this.seats[i];
            s.seatindex = i;
            s.score = null;
            s.holds = baseInfo.game_seats[i];
            s.pengs = [];
            s.angangs = [];
            s.diangangs = [];
            s.wangangs = [];
            s.folds = [];
            console.log(s);
            if (cc.vv.userMgr.userId == s.userid) {
                this.seatIndex = i;
            }
        }
        this.conf = {
            type: baseInfo.type,
        }
        if (this.conf.type == null) {
            this.conf.type == "xzdd";
        }
    }

    getWanfa() {
        var conf = this.conf;
        if (conf && conf.maxGames != null && conf.maxFan != null) {
            var strArr = [];
            strArr.push(conf.maxGames + "局");
            strArr.push(conf.maxFan + "番封顶");
            if (conf.hsz) {
                strArr.push("换三张");
            }
            if (conf.zimo == 1) {
                strArr.push("自摸加番");
            }
            else {
                strArr.push("自摸加底");
            }
            if (conf.jiangdui) {
                strArr.push("将对");
            }
            if (conf.dianganghua == 1) {
                strArr.push("点杠花(自摸)");
            }
            else {
                strArr.push("点杠花(放炮)");
            }
            if (conf.menqing) {
                strArr.push("门清、中张");
            }
            if (conf.tiandihu) {
                strArr.push("天地胡");
            }
            return strArr.join(" ");
        }
        return "";
    }

    initHandlers() {
        var self = this;
        cc.vv.net.addHandler("login_result", function (data) {
            console.log(data);
            var resp = data as LoginResultPush;
            if (resp.errcode === 0) {
                var loginData = resp.data!;
                self.roomId = loginData.roomid;
                self.conf = loginData.conf;
                self.maxNumOfGames = loginData.conf.maxGames as number;
                self.numOfGames = loginData.numofgames;
                self.seats = loginData.seats;
                self.seatIndex = self.getSeatIndexByID(cc.vv.userMgr.userId as number);
                self.isOver = false;
            }
            else {
                console.log(resp.errmsg);
                // 进房被拒里的"账号已被封禁"（服务端 errcode=4，见
                // `game_server/socket_service.ts` 的封禁校验）：这时没有建立对局连接，
                // 玩家停在"正在进入房间"的等待遮罩上，必须提示并收回遮罩。
                // 其它错误码维持原样（只打日志），不改变既有行为。
                if (resp.errcode === ERR_ACCOUNT_BANNED) {
                    cc.vv.wc.hide();
                    cc.vv.alert!.show("无法进入房间", resp.errmsg ? String(resp.errmsg) : "账号已被封禁");
                }
            }
            self.dispatchEvent('login_result');
        });

        cc.vv.net.addHandler("login_finished", function (data) {
            console.log("login_finished");
            cc.director.loadScene("mjgame", function () {
                cc.vv.net.ping();
                cc.vv.wc.hide();
            });
            self.dispatchEvent("login_finished");
        });

        cc.vv.net.addHandler("exit_result", function (data) {
            self.roomId = null;
            self.turn = -1;
            self.dingque = -1;
            self.isDingQueing = false;
            self.seats = null;
        });

        cc.vv.net.addHandler("exit_notify_push", function (data) {
            var userId = data as number;
            var s = self.getSeatByID(userId);
            if (s != null) {
                s.userid = 0;
                s.name = "";
                self.dispatchEvent("user_state_changed", s);
            }
        });

        cc.vv.net.addHandler("dispress_push", function (data) {
            self.roomId = null;
            self.turn = -1;
            self.dingque = -1;
            self.isDingQueing = false;
            self.seats = null;
        });

        cc.vv.net.addHandler("disconnect", function (data) {
            if (self.roomId == null) {
                cc.vv.wc.show('正在返回游戏大厅');
                cc.director.loadScene("hall");
            }
            else {
                if (self.isOver == false) {
                    cc.vv.userMgr.oldRoomId = self.roomId;
                    self.dispatchEvent("disconnect");
                }
                else {
                    self.roomId = null;
                }
            }
        });

        cc.vv.net.addHandler("new_user_comes_push", function (data) {
            //console.log(data);
            var seat = data as SeatData;
            var seatIndex = seat.seatindex;
            var needCheckIp = false;
            if (self.seats![seatIndex].userid > 0) {
                self.seats![seatIndex].online = true;
                if (self.seats![seatIndex].ip != seat.ip) {
                    self.seats![seatIndex].ip = seat.ip;
                    needCheckIp = true;
                }
            }
            else {
                seat.online = true;
                self.seats![seatIndex] = seat;
                needCheckIp = true;
            }
            self.dispatchEvent('new_user', self.seats![seatIndex]);

            if (needCheckIp) {
                self.dispatchEvent('check_ip', self.seats![seatIndex]);
            }
        });

        cc.vv.net.addHandler("user_state_push", function (data) {
            //console.log(data);
            var push = data as UserStatePush;
            var userId = push.userid;
            var seat = self.getSeatByID(userId);
            seat.online = push.online;
            self.dispatchEvent('user_state_changed', seat);
        });

        cc.vv.net.addHandler("user_ready_push", function (data) {
            //console.log(data);
            var push = data as UserReadyPush;
            var userId = push.userid;
            var seat = self.getSeatByID(userId);
            seat.ready = push.ready;
            self.dispatchEvent('user_state_changed', seat);
        });

        cc.vv.net.addHandler("game_holds_push", function (data) {
            var holds = data as PaiList;
            var seat = self.seats![self.seatIndex];
            console.log(holds);
            seat.holds = holds;

            for (var i = 0; i < self.seats!.length; ++i) {
                var s = self.seats![i];
                if (s.folds == null) {
                    s.folds = [];
                }
                if (s.pengs == null) {
                    s.pengs = [];
                }
                if (s.angangs == null) {
                    s.angangs = [];
                }
                if (s.diangangs == null) {
                    s.diangangs = [];
                }
                if (s.wangangs == null) {
                    s.wangangs = [];
                }
                s.ready = false;
            }
            self.dispatchEvent('game_holds');
        });

        cc.vv.net.addHandler("game_begin_push", function (data) {
            console.log('game_action_push');
            console.log(data);
            self.button = data as number;
            self.turn = self.button;
            self.gamestate = "begin";
            self.dispatchEvent('game_begin');
        });

        cc.vv.net.addHandler("game_playing_push", function (data) {
            console.log('game_playing_push');
            self.gamestate = "playing";
            self.dispatchEvent('game_playing');
        });

        cc.vv.net.addHandler("game_sync_push", function (data) {
            console.log("game_sync_push");
            console.log(data);
            var sync = data as GameSyncPush;
            self.numOfMJ = sync.numofmj;
            self.gamestate = sync.state;
            if (self.gamestate == "dingque") {
                self.isDingQueing = true;
            }
            else if (self.gamestate == "huanpai") {
                self.isHuanSanZhang = true;
            }
            self.turn = sync.turn;
            self.button = sync.button;
            self.chupai = sync.chuPai;
            self.huanpaimethod = sync.huanpaimethod;
            for (var i = 0; i < 4; ++i) {
                var seat = self.seats![i];
                var sd = sync.seats[i];
                seat.holds = sd.holds as PaiList;
                seat.folds = sd.folds;
                seat.angangs = sd.angangs;
                seat.diangangs = sd.diangangs;
                seat.wangangs = sd.wangangs;
                seat.pengs = sd.pengs;
                seat.dingque = sd.que;
                seat.hued = sd.hued;
                seat.iszimo = sd.iszimo;
                seat.huinfo = sd.huinfo;
                seat.huanpais = sd.huanpais;
                if (i == self.seatIndex) {
                    self.dingque = sd.que;
                }
            }
            self.dispatchEvent('game_sync');
        });

        cc.vv.net.addHandler("game_dingque_push", function (data) {
            self.isDingQueing = true;
            self.isHuanSanZhang = false;
            self.gamestate = 'dingque';
            self.dispatchEvent('game_dingque');
        });

        cc.vv.net.addHandler("game_huanpai_push", function (data) {
            self.isHuanSanZhang = true;
            self.dispatchEvent('game_huanpai');
        });

        cc.vv.net.addHandler("hangang_notify_push", function (data) {
            self.dispatchEvent('hangang_notify', data);
        });

        cc.vv.net.addHandler("game_action_push", function (data) {
            self.curaction = data as ActionPushData;
            console.log(data);
            self.dispatchEvent('game_action', data);
        });

        cc.vv.net.addHandler("game_chupai_push", function (data) {
            console.log('game_chupai_push');
            //console.log(data);
            var turnUserID = data as number;
            var si = self.getSeatIndexByID(turnUserID);
            self.doTurnChange(si);
        });

        cc.vv.net.addHandler("game_num_push", function (data) {
            self.numOfGames = data as number;
            self.dispatchEvent('game_num', data);
        });

        cc.vv.net.addHandler("game_over_push", function (data) {
            console.log('game_over_push');
            var push = data as GameOverPush;
            var results = push.results;
            for (var i = 0; i < self.seats!.length; ++i) {
                self.seats![i].score = results.length == 0 ? 0 : results[i].totalscore;
            }
            self.dispatchEvent('game_over', results);
            if (push.endinfo) {
                self.isOver = true;
                self.dispatchEvent('game_end', push.endinfo);
            }
            self.reset();
            for (var i = 0; i < self.seats!.length; ++i) {
                self.dispatchEvent('user_state_changed', self.seats![i]);
            }
        });

        cc.vv.net.addHandler("mj_count_push", function (data) {
            console.log('mj_count_push');
            self.numOfMJ = data as number;
            //console.log(data);
            self.dispatchEvent('mj_count', data);
        });

        cc.vv.net.addHandler("hu_push", function (data) {
            console.log('hu_push');
            console.log(data);
            self.doHu(data as HuPush);
        });

        cc.vv.net.addHandler("game_chupai_notify_push", function (data) {
            var push = data as ChupaiNotifyPush;
            var userId = push.userId;
            var pai = push.pai;
            var si = self.getSeatIndexByID(userId);
            self.doChupai(si, pai);
        });

        cc.vv.net.addHandler("game_mopai_push", function (data) {
            console.log('game_mopai_push');
            self.doMopai(self.seatIndex, data as Pai);
        });

        cc.vv.net.addHandler("guo_notify_push", function (data) {
            console.log('guo_notify_push');
            var push = data as ChupaiNotifyPush;
            var userId = push.userId;
            var pai = push.pai;
            var si = self.getSeatIndexByID(userId);
            self.doGuo(si, pai);
        });

        cc.vv.net.addHandler("guo_result", function (data) {
            console.log('guo_result');
            self.dispatchEvent('guo_result');
        });

        cc.vv.net.addHandler("guohu_push", function (data) {
            console.log('guohu_push');
            self.dispatchEvent("push_notice", { info: "过胡", time: 1.5 });
        });

        cc.vv.net.addHandler("huanpai_notify", function (data) {
            var push = data as HuanPaiNotifyPush;
            var seat = self.getSeatByID(push.si as number);
            seat.huanpais = push.huanpais as PaiList | null;
            self.dispatchEvent('huanpai_notify', seat);
        });

        cc.vv.net.addHandler("game_huanpai_over_push", function (data) {
            console.log('game_huanpai_over_push');
            var push = data as HuanPaiNotifyPush;
            var info = "";
            var method = push.method;
            if (method == 0) {
                info = "换对家牌";
            }
            else if (method == 1) {
                info = "换下家牌";
            }
            else {
                info = "换上家牌";
            }
            self.huanpaimethod = method;
            cc.vv.gameNetMgr.isHuanSanZhang = false;
            self.dispatchEvent("game_huanpai_over");
            self.dispatchEvent("push_notice", { info: info, time: 2 });
        });

        cc.vv.net.addHandler("peng_notify_push", function (data) {
            console.log('peng_notify_push');
            console.log(data);
            var push = data as PengNotifyPush;
            var userId = push.userid;
            var pai = push.pai;
            var si = self.getSeatIndexByID(userId);
            self.doPeng(si, pai);
        });

        cc.vv.net.addHandler("gang_notify_push", function (data) {
            console.log('gang_notify_push');
            console.log(data);
            var push = data as GangNotifyPush;
            var userId = push.userid;
            var pai = push.pai;
            var si = self.getSeatIndexByID(userId);
            self.doGang(si, pai, push.gangtype);
        });

        cc.vv.net.addHandler("game_dingque_notify_push", function (data) {
            self.dispatchEvent('game_dingque_notify', data);
        });

        cc.vv.net.addHandler("game_dingque_finish_push", function (data) {
            var queList = data as number[];
            for (var i = 0; i < queList.length; ++i) {
                self.seats![i].dingque = queList[i];
                if (i == self.seatIndex) {
                    self.dingque = queList[i];
                }
            }
            self.dispatchEvent('game_dingque_finish', queList);
        });

        cc.vv.net.addHandler("chat_push", function (data) {
            self.dispatchEvent("chat_push", data);
        });

        cc.vv.net.addHandler("quick_chat_push", function (data) {
            self.dispatchEvent("quick_chat_push", data);
        });

        cc.vv.net.addHandler("emoji_push", function (data) {
            self.dispatchEvent("emoji_push", data);
        });

        cc.vv.net.addHandler("dissolve_notice_push", function (data) {
            console.log("dissolve_notice_push");
            console.log(data);
            self.dissoveData = data as DissolveNoticePush;
            self.dispatchEvent("dissolve_notice", data);
        });

        cc.vv.net.addHandler("dissolve_cancel_push", function (data) {
            self.dissoveData = null;
            self.dispatchEvent("dissolve_cancel", data);
        });

        cc.vv.net.addHandler("voice_msg_push", function (data) {
            self.dispatchEvent("voice_msg", data);
        });
    }

    doGuo(seatIndex: number, pai: Pai) {
        var seatData = this.seats![seatIndex];
        var folds = seatData.folds;
        folds.push(pai);
        this.dispatchEvent('guo_notify', seatData);
    }

    doMopai(seatIndex: number, pai: Pai) {
        var seatData = this.seats![seatIndex];
        if (seatData.holds) {
            seatData.holds.push(pai);
            this.dispatchEvent('game_mopai', { seatIndex: seatIndex, pai: pai });
        }
    }

    doChupai(seatIndex: number, pai: Pai) {
        this.chupai = pai;
        var seatData = this.seats![seatIndex];
        if (seatData.holds) {
            var idx = seatData.holds.indexOf(pai);
            seatData.holds.splice(idx, 1);
        }
        this.dispatchEvent('game_chupai_notify', { seatData: seatData, pai: pai });
    }

    doPeng(seatIndex: number, pai: Pai) {
        var seatData = this.seats![seatIndex];
        //移除手牌
        if (seatData.holds) {
            for (var i = 0; i < 2; ++i) {
                var idx = seatData.holds.indexOf(pai);
                seatData.holds.splice(idx, 1);
            }
        }

        //更新碰牌数据
        var pengs = seatData.pengs;
        pengs.push(pai);

        this.dispatchEvent('peng_notify', seatData);
    }

    getGangType(seatData: SeatData, pai: Pai) {
        if (seatData.pengs.indexOf(pai) != -1) {
            return "wangang";
        }
        else {
            var cnt = 0;
            for (var i = 0; i < seatData.holds.length; ++i) {
                if (seatData.holds[i] == pai) {
                    cnt++;
                }
            }
            if (cnt == 3) {
                return "diangang";
            }
            else {
                return "angang";
            }
        }
    }

    doGang(seatIndex: number, pai: Pai, gangtype?: string) {
        var seatData = this.seats![seatIndex];

        if (!gangtype) {
            gangtype = this.getGangType(seatData, pai);
        }

        if (gangtype == "wangang") {
            if (seatData.pengs.indexOf(pai) != -1) {
                var idx = seatData.pengs.indexOf(pai);
                if (idx != -1) {
                    seatData.pengs.splice(idx, 1);
                }
            }
            seatData.wangangs.push(pai);
        }
        if (seatData.holds) {
            for (var i = 0; i <= 4; ++i) {
                var idx = seatData.holds.indexOf(pai);
                if (idx == -1) {
                    //如果没有找到，表示移完了，直接跳出循环
                    break;
                }
                seatData.holds.splice(idx, 1);
            }
        }
        if (gangtype == "angang") {
            seatData.angangs.push(pai);
        }
        else if (gangtype == "diangang") {
            seatData.diangangs.push(pai);
        }
        this.dispatchEvent('gang_notify', { seatData: seatData, gangtype: gangtype });
    }

    doHu(data: HuPush) {
        this.dispatchEvent('hupai', data);
    }

    doTurnChange(si: number) {
        var data = {
            last: this.turn,
            turn: si,
        }
        this.turn = si;
        this.dispatchEvent('game_chupai', data);
    }

    connectGameServer(data: HttpResp) {
        this.dissoveData = null;
        cc.vv.net.ip = data.ip + ":" + data.port;
        console.log(cc.vv.net.ip);
        var self = this;

        var onConnectOK = function () {
            console.log("onConnectOK");
            var sd: LoginHandshake = {
                token: data.token as string,
                roomid: data.roomid as string,
                time: data.time as number,
                sign: data.sign as string,
            };
            cc.vv.net.send("login", sd);
        };

        var onConnectFailed = function () {
            console.log("failed.");
            cc.vv.wc.hide();
        };
        cc.vv.wc.show("正在进入房间");
        cc.vv.net.connect(onConnectOK, onConnectFailed);
    }
    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = GameNetMgr;
