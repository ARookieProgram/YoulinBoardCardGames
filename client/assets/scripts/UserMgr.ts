// 用户管理器：游客鉴权、登录、创建角色、进房间与战绩查询。
//
// 本文件用 ES6 class + @ccclass/@property 装饰器（Creator 2.4 的官方写法）：
// 运行时行为与迁移前的 UserMgr.js 完全一致，只补了类型标注与跨网络边界的断言。

const { ccclass, property } = cc._decorator;

/**
 * 大厅服在"账号被封禁"时返回的业务码（`server/hall_server/client_service.ts` /
 * `server-python/hall_server/client_service.py` 的 `ERR_ACCOUNT_BANNED`）。
 * 正常登录是 0，1 是参数不全，2 是历史遗留的 login failed。
 */
const ERR_ACCOUNT_BANNED = 3;

@ccclass
export default class UserMgr extends cc.Component {
    @property account: string | number | null = null;
    @property userId: number | null = null;
    @property userName: string | null = null;
    @property lv: number = 0;
    @property exp: number = 0;
    @property coins: number = 0;
    @property gems: number = 0;
    @property sign: string | number | null = 0;
    @property ip: string = "";
    @property sex: number = 0;
    @property roomData: string | null = null;

    @property oldRoomId: string | null = null;

    guestAuth() {
        var account: string | number | null = cc.args["account"];
        if (account == null) {
            account = cc.sys.localStorage.getItem("account");
        }

        if (account == null) {
            account = Date.now();
            cc.sys.localStorage.setItem("account", account);
        }

        cc.vv.http.sendRequest("/guest", { account: account }, this.onAuth);
    }

    onAuth(ret: HttpResp) {
        var self = cc.vv.userMgr;
        if (ret.errcode !== 0) {
            console.log(ret.errmsg);
        }
        else {
            self.account = ret.account!;
            self.sign = ret.sign!;
            cc.vv.http.url = "http://" + cc.vv.SI.hall;
            self.login();
        }
    }

    login() {
        var self = this;
        var onLogin = function (ret: HttpResp) {
            if (ret.errcode !== 0) {
                console.log(ret.errmsg);
                // 封禁是服务端（大厅服）在登录时就拦下的状态：必须让玩家看到原因，
                // 否则界面上只会留一个不会消失的"正在登录游戏"。
                // `errmsg` 由服务端拼好（原因 / 自动解封时间），原样展示。
                if (ret.errcode === ERR_ACCOUNT_BANNED) {
                    cc.vv.wc.hide();
                    cc.vv.alert!.show("无法登录", ret.errmsg ? String(ret.errmsg) : "账号已被封禁");
                }
            }
            else {
                if (!ret.userid) {
                    //jump to register user info.
                    cc.director.loadScene("createrole");
                }
                else {
                    console.log(ret);
                    self.account = ret.account!;
                    self.userId = ret.userid!;
                    self.userName = ret.name!;
                    self.lv = ret.lv!;
                    self.exp = ret.exp!;
                    self.coins = ret.coins!;
                    self.gems = ret.gems!;
                    self.roomData = ret.roomid!;
                    self.sex = ret.sex!;
                    self.ip = ret.ip!;
                    cc.director.loadScene("hall");
                }
            }
        };
        cc.vv.wc.show("正在登录游戏");
        cc.vv.http.sendRequest("/login", { account: this.account, sign: this.sign }, onLogin);
    }

    create(name: string) {
        var self = this;
        var onCreate = function (ret: HttpResp) {
            if (ret.errcode !== 0) {
                console.log(ret.errmsg);
            }
            else {
                self.login();
            }
        };

        var data = {
            account: this.account,
            sign: this.sign,
            name: name
        };
        cc.vv.http.sendRequest("/create_user", data, onCreate);
    }

    enterRoom(roomId: string | number | null, callback?: (ret: HttpResp) => void) {
        var self = this;
        var onEnter = function (ret: HttpResp) {
            if (ret.errcode !== 0) {
                if (ret.errcode == -1) {
                    setTimeout(function () {
                        self.enterRoom(roomId, callback);
                    }, 5000);
                }
                else {
                    cc.vv.wc.hide();
                    if (callback != null) {
                        callback(ret);
                    }
                }
            }
            else {
                cc.vv.wc.hide();
                if (callback != null) {
                    callback(ret);
                }
                cc.vv.gameNetMgr.connectGameServer(ret);
            }
        };

        var data = {
            account: cc.vv.userMgr.account,
            sign: cc.vv.userMgr.sign,
            roomid: roomId
        };
        cc.vv.wc.show("正在进入房间 " + roomId);
        cc.vv.http.sendRequest("/enter_private_room", data, onEnter);
    }

    getHistoryList(callback: (history: unknown) => void) {
        var self = this;
        var onGet = function (ret: HttpResp) {
            if (ret.errcode !== 0) {
                console.log(ret.errmsg);
            }
            else {
                console.log(ret.history);
                if (callback != null) {
                    callback(ret.history);
                }
            }
        };

        var data = {
            account: cc.vv.userMgr.account,
            sign: cc.vv.userMgr.sign,
        };
        cc.vv.http.sendRequest("/get_history_list", data, onGet);
    }

    getGamesOfRoom(uuid: string, callback: (data: unknown) => void) {
        var self = this;
        var onGet = function (ret: HttpResp) {
            if (ret.errcode !== 0) {
                console.log(ret.errmsg);
            }
            else {
                console.log(ret.data);
                callback(ret.data);
            }
        };

        var data = {
            account: cc.vv.userMgr.account,
            sign: cc.vv.userMgr.sign,
            uuid: uuid,
        };
        cc.vv.http.sendRequest("/get_games_of_room", data, onGet);
    }

    getDetailOfGame(uuid: string, index: number, callback: (data: unknown) => void) {
        var self = this;
        var onGet = function (ret: HttpResp) {
            if (ret.errcode !== 0) {
                console.log(ret.errmsg);
            }
            else {
                console.log(ret.data);
                callback(ret.data);
            }
        };

        var data = {
            account: cc.vv.userMgr.account,
            sign: cc.vv.userMgr.sign,
            uuid: uuid,
            index: index,
        };
        cc.vv.http.sendRequest("/get_detail_of_game", data, onGet);
    }
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = UserMgr;
