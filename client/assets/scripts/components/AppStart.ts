// 启动入口：组装 cc.vv 单例、初始化各管理器、解析启动参数，最后决定进哪个场景。
//
// 本文件是 ES5 风格（cc.Class / var / function）的 TypeScript 迁移产物：
// 运行时行为与迁移前的 AppStart.js 完全一致，只补了类型标注与跨网络边界的断言。

// `showSplash` 与 `cc.loader.load` 的回调都通过 `.bind(this)` 绑到组件实例上；
// 这里只声明这些回调里真正用到的成员，供 tsc 解析回调中的 `this`（不影响运行时）。
interface AppStartSelf {
    getServerInfo(): void;
}

function urlParse(): { [key: string]: string } {
    var params: { [key: string]: string } = {};
    if (window.location == null) {
        return params;
    }
    var name: string, value: string;
    var str = window.location.href; //取得整个地址栏
    var num = str.indexOf("?")
    str = str.substr(num + 1); //取得所有参数   stringvar.substr(start [, length ]

    var arr = str.split("&"); //各个参数放到数组里
    for (var i = 0; i < arr.length; i++) {
        num = arr[i].indexOf("=");
        if (num > 0) {
            name = arr[i].substring(0, num);
            value = arr[i].substr(num + 1);
            params[name] = value;
        }
    }
    return params;
}

function initMgr() {
    cc.vv = {} as CCVV;
    var UserMgr = require("UserMgr") as UserMgrConstructor;
    cc.vv.userMgr = new UserMgr();

    var ReplayMgr = require("ReplayMgr") as ReplayMgrConstructor;
    cc.vv.replayMgr = new ReplayMgr();

    cc.vv.http = require("HTTP") as HttpModule;
    cc.vv.global = require("Global") as GlobalClass;
    cc.vv.net = require("Net") as NetClass;

    var GameNetMgr = require("GameNetMgr") as GameNetMgrConstructor;
    cc.vv.gameNetMgr = new GameNetMgr();
    cc.vv.gameNetMgr.initHandlers();

    var AnysdkMgr = require("AnysdkMgr") as AnysdkMgrConstructor;
    cc.vv.anysdkMgr = new AnysdkMgr();
    cc.vv.anysdkMgr.init();

    var VoiceMgr = require("VoiceMgr") as VoiceMgrConstructor;
    cc.vv.voiceMgr = new VoiceMgr();
    cc.vv.voiceMgr.init();

    var AudioMgr = require("AudioMgr") as AudioMgrConstructor;
    cc.vv.audioMgr = new AudioMgr();
    cc.vv.audioMgr.init();

    var Utils = require("Utils") as UtilsConstructor;
    cc.vv.utils = new Utils();

    //var MJUtil = require("MJUtil");
    //cc.vv.mjutil = new MJUtil();

    cc.args = urlParse();
}

cc.Class({
    extends: cc.Component,

    properties: {
        // foo: {
        //    default: null,      // The default value will be used only when the component attaching
        //                           to a node for the first time
        //    url: cc.Texture2D,  // optional, default is typeof default
        //    serializable: true, // optional, default is true
        //    visible: true,      // optional, default is true
        //    displayName: 'Foo', // optional
        //    readonly: false,    // optional, default is false
        // },
        // ...
        label: {
            default: null as cc.Label | null,
            type:cc.Label
        },

        // Creator 的属性简写：值就是类型构造器本身，运行时仍是 `cc.Label`；
        // 这里用一次断言把 `this.loadingProgess` 收窄成 Label 实例类型。
        loadingProgess:cc.Label as unknown as cc.Label,
    },

    // 以下两个字段老代码是运行时动态挂到实例上的，**不在 properties 里**。
    // 这里写上 `undefined` 只是为了在类型层面说明它们的存在：prototype 上的值仍是 undefined，
    // 运行时状态与「字段不存在」完全一致，没有补任何初始值。
    _mainScene: undefined as string | undefined,
    _splash: undefined as cc.Node | undefined,

    // use this for initialization
    onLoad: function () {
        initMgr();
        cc.vv.utils.setFitSreenMode();
        console.log('haha');
        this._mainScene = 'loading';
        this.showSplash(function (this: AppStartSelf) {
            this.getServerInfo();
        }.bind(this));
    },

    onBtnDownloadClicked:function(){
        cc.sys.openURL(cc.vv.SI.appweb);
    },

    showSplash:function(callback: () => void){
        var self = this;
        var SHOW_TIME = 3000;
        var FADE_TIME = 500;
        this._splash = cc.find("Canvas/splash");
        if(true || cc.sys.os != cc.sys.OS_IOS || !cc.sys.isNative){
            this._splash!.active = true;
            // getComponent 只声明返回 Component，这里断言成节点上实际挂着的 Sprite。
            if((this._splash!.getComponent(cc.Sprite) as cc.Sprite).spriteFrame == null){
                callback();
                return;
            }
            var t = Date.now();
            var fn: () => void = function(){
                var dt = Date.now() - t;
                if(dt < SHOW_TIME){
                    setTimeout(fn,33);
                }
                else {
                    var op = (1 - ((dt - SHOW_TIME) / FADE_TIME)) * 255;
                    if(op < 0){
                        self._splash!.opacity = 0;
                        callback();
                    }
                    else{
                        self._splash!.opacity = op;
                        setTimeout(fn,33);
                    }
                }
            };
            setTimeout(fn,33);
        }
        else{
            this._splash!.active = false;
            callback();
        }
    },

    getServerInfo:function(){
        var self = this;
        var onGetVersion = function (this: void, ret: HttpResp) {
            // 网络边界：/get_serverinfo 的返回体就是 ServerInfo。HTTP 回调统一按 HttpResp 收口，
            // 两者的必填字段不同（一个要 errcode、一个要 hall/appweb/version），所以经 unknown 断言一次。
            cc.vv.SI = ret as unknown as ServerInfo;
            if(cc.sys.isNative){
                var url = cc.url.raw('resources/ver/cv.txt');
                cc.loader.load(url,function(err: Error | null,data: string){
                    cc.VERSION = data;
                    if(ret.version == null){
                        console.log("error.");
                    }
                    else{
                        if(ret.version != cc.VERSION){
                            cc.find("Canvas/alert").active = true;
                        }
                        else{
                            cc.director.loadScene(self._mainScene!);
                        }
                    }
                }.bind(this));
            }
            else{
                cc.director.loadScene(self._mainScene!);
            }
        };

        var xhr: XMLHttpRequest | null = null;
        var complete = false;
        // fnRequest 与 fn 互相引用，这里显式写出函数类型，避免 tsc 推断成循环的隐式 any。
        var fnRequest: () => void = function(){
            self.loadingProgess.string = "正在连接服务器";
            xhr = cc.vv.http.sendRequest("/get_serverinfo",null,function(ret: HttpResp){
                xhr = null;
                complete = true;
                onGetVersion(ret);
            });
            setTimeout(fn,5000);
        }

        var fn: () => void = function(){
            if(!complete){
                if(xhr){
                    xhr.abort();
                    self.loadingProgess.string = "连接失败，即将重试";
                    setTimeout(function(){
                        fnRequest();
                    },5000);
                }
                else{
                    fnRequest();
                }
            }
        };
        fn();
    },
    log:function(content: string){
        this.label!.string += content + '\n';
    },
});

export { };
