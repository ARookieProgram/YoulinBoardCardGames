// 启动入口：组装 cc.vv 单例、初始化各管理器、解析启动参数，最后决定进哪个场景。
//
// 本文件用 ES6 class + @ccclass/@property 装饰器（Creator 2.4 的官方写法）：
// 运行时行为与迁移前的 AppStart.js 完全一致，只补了类型标注与跨网络边界的断言。

// `showSplash` 与 `cc.loader.load` 的回调都通过 `.bind(this)` 绑到组件实例上；
// 这里只声明这些回调里真正用到的成员，供 tsc 解析回调中的 `this`（不影响运行时）。
interface AppStartSelf {
    getServerInfo(): void;
}

/**
 * 隐藏左下角的帧率 / draw call 等引擎统计信息（**所有场景**）。
 *
 * Creator 的预览模板（`preview-templates/boot.js`）默认把 `showFPS` 传成 true，所以每个场景
 * 左下角都会显示这些信息；本工程没有任何地方需要它。`cc.debug.setDisplayStats(false)` 会同时把
 * `cc.game.config.showFPS` 置成 false，引擎随后在 `_runMainLoop` 里再读配置时也不会把它打开。
 *
 * 之所以在模块顶层就调一次：Creator 会把 `assets/` 下的脚本整包加载
 * （`temp/quick-scripts` 下的 `__qc_bundle__.js`），所以**预览任意一个场景**都会执行到这里，
 * 而不只是从 `start` 场景进游戏时。`onLoad` 里再调一次兜底，防止模块执行时配置还没就绪。
 */
function hideDisplayStats(): void {
    // `cc.game.config` 由 `cc.game.init()` 写入；模块顶层执行时它一般已经存在，
    // 极端时序下取不到就先跳过，交给 onLoad 的那次调用。
    if (cc.game.config == null) {
        return;
    }
    cc.debug.setDisplayStats(false);
}

hideDisplayStats();

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

const { ccclass, property } = cc._decorator;

@ccclass
export default class AppStart extends cc.Component {
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
    @property({type: cc.Label}) label: cc.Label | null = null as cc.Label | null;
    // 老写法是简写 `loadingProgess: cc.Label`：引擎会规范化成 { default: null, type: cc.Label }。
    // 这里用 @property(cc.Label) 写出同一个元数据，初值就是那个 null（字段类型沿用迁移时的 cc.Label）。
    @property(cc.Label) loadingProgess: cc.Label = null as unknown as cc.Label;

    // 以下字段老代码是运行时动态挂到实例上的，**不是 Creator 的序列化属性**。
    // 这里用 declare 只声明类型、不产生运行时代码：与「字段不存在」完全一致，没有补任何初始值。
    declare _mainScene: string | undefined;
    declare _splash: cc.Node | undefined;

    // use this for initialization
    onLoad() {
        // 兜底：模块顶层那次调用若因配置未就绪被跳过，这里补上（见 hideDisplayStats 的说明）。
        hideDisplayStats();
        initMgr();
        cc.vv.utils.setFitSreenMode();
        console.log('haha');
        this._mainScene = 'loading';
        this.showSplash(function (this: AppStartSelf) {
            this.getServerInfo();
        }.bind(this));
    }

    onBtnDownloadClicked(){
        cc.sys.openURL(cc.vv.SI.appweb);
    }

    showSplash(callback: () => void){
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
    }

    getServerInfo(){
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
    }

    log(content: string){
        this.label!.string += content + '\n';
    }
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = AppStart;
