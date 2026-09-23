// 用户管理器：游客鉴权、登录、创建角色、进房间与战绩查询。
//
// 本文件是 ES5 风格（cc.Class / var / function）的 TypeScript 迁移产物：
// 运行时行为与迁移前的 UserMgr.js 完全一致，只补了类型标注与跨网络边界的断言。
cc.Class({
    extends: cc.Component,
    properties: {
        account: null as string | number | null,
        userId: null as number | null,
        userName: null as string | null,
        lv: 0,
        exp: 0,
        coins: 0,
        gems: 0,
        sign: 0 as string | number | null,
        ip: "",
        sex: 0,
        roomData: null as string | null,

        oldRoomId: null as string | null,
    },

    guestAuth: function () {
        var account: string | number | null = cc.args["account"];
        if (account == null) {
            account = cc.sys.localStorage.getItem("account");
        }

        if (account == null) {
            account = Date.now();
            cc.sys.localStorage.setItem("account", account);
        }

        cc.vv.http.sendRequest("/guest", { account: account }, this.onAuth);
    },

    onAuth: function (ret: HttpResp) {
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
    },

    login: function () {
        var self = this;
        var onLogin = function (ret: HttpResp) {
            if (ret.errcode !== 0) {
                console.log(ret.errmsg);
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
    },

    create: function (name: string) {
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
    },

    enterRoom: function (roomId: string | number | null, callback?: (ret: HttpResp) => void) {
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
    },
    getHistoryList: function (callback: (history: unknown) => void) {
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
    },
    getGamesOfRoom: function (uuid: string, callback: (data: unknown) => void) {
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
    },

    getDetailOfGame: function (uuid: string, index: number, callback: (data: unknown) => void) {
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
});

export { };
