// 大厅主界面：用户信息、公告、宝石提示与各功能入口。
//
// 本文件是 ES5 风格（cc.Class / var / function）的 TypeScript 迁移产物：
// 运行时行为与迁移前的 Hall.js 完全一致，只补了类型标注与跨网络边界的断言。

/**
 * `refreshInfo` / `refreshGemsTip` / `refreshNotice` 的 HTTP 回调与 `onBtnAddGemsClicked`
 * 的确认回调都通过 `.bind(this)` 绑到组件实例上；这里只声明这些回调里真正用到的成员，
 * 供 tsc 解析回调中的 `this`（可擦除，不影响运行时）。
 */
interface HallSelf {
    lblGems: cc.Label | null;
    lblNotice: cc.Label | null;
    onBtnTaobaoClicked(): void;
}

/** 节点上按类名取到的 `ImageLoader` 组件；creator.d.ts 的字符串重载只返回 `cc.Component`。 */
interface ImageLoaderApi extends cc.Component {
    /** 0（含 null）表示取不到用户，组件内部直接返回。 */
    setUserID(userId: number | null): void;
}

/** `/get_message`（公告与宝石提示共用）的返回体：在通用响应上多了 `msg`（`version` 共享声明里已有）。 */
interface MessageResp extends HttpResp {
    msg: string;
}

// 这两行老代码里就没有用到（只是加载模块），原样保留；`require` 的返回值按 `unknown` 收口。
var Net = require("Net")
var Global = require("Global")
cc.Class({
    extends: cc.Component,

    properties: {
        // 这几项原来的值就是「类型」本身（运行期 Creator 读到的仍是构造函数），
        // 这里只加可擦除的断言把它标成实例类型，运行时行为不变。
        lblName:cc.Label as unknown as cc.Label | null,
        lblMoney:cc.Label as unknown as cc.Label | null,
        lblGems:cc.Label as unknown as cc.Label | null,
        lblID:cc.Label as unknown as cc.Label | null,
        lblNotice:cc.Label as unknown as cc.Label | null,
        joinGameWin:cc.Node as unknown as cc.Node | null,
        createRoomWin:cc.Node as unknown as cc.Node | null,
        settingsWin:cc.Node as unknown as cc.Node | null,
        helpWin:cc.Node as unknown as cc.Node | null,
        xiaoxiWin:cc.Node as unknown as cc.Node | null,
        btnJoinGame:cc.Node as unknown as cc.Node | null,
        btnReturnGame:cc.Node as unknown as cc.Node | null,
        sprHeadImg:cc.Sprite as unknown as cc.Sprite | null,
        // foo: {
        //    default: null,
        //    url: cc.Texture2D,  // optional, default is typeof default
        //    serializable: true, // optional, default is true
        //    visible: true,      // optional, default is true
        //    displayName: 'Foo', // optional
        //    readonly: false,    // optional, default is false
        // },
        // ...
    },
    
    initNetHandlers:function(){
        var self = this;
    },
    
    onShare:function(){
        cc.vv.anysdkMgr.share("天天麻将","天天麻将，包含了血战到底、血流成河等多种四川流行麻将玩法。");   
    },

    // use this for initialization
    onLoad: function () {
        cc.vv.utils.setFitSreenMode();
        this.initLabels();
        
        if(cc.vv.gameNetMgr.roomId == null){
            this.btnJoinGame!.active = true;
            this.btnReturnGame!.active = false;
        }
        else{
            this.btnJoinGame!.active = false;
            this.btnReturnGame!.active = true;
        }
        
        //var params = cc.vv.args;
        var roomId = cc.vv.userMgr.oldRoomId 
        if( roomId != null){
            cc.vv.userMgr.oldRoomId = null;
            cc.vv.userMgr.enterRoom(roomId);
        }
        
        var imgLoader = this.sprHeadImg!.node.getComponent("ImageLoader") as ImageLoaderApi;
        imgLoader.setUserID(cc.vv.userMgr.userId);
        cc.vv.utils.addClickEvent(this.sprHeadImg!.node,this.node,"Hall","onBtnClicked");
        
        
        this.addComponent("UserInfoShow");
        
        this.initButtonHandler("Canvas/right_bottom/btn_shezhi");
        this.initButtonHandler("Canvas/right_bottom/btn_help");
        this.initButtonHandler("Canvas/right_bottom/btn_xiaoxi");
        this.helpWin!.addComponent("OnBack");
        this.xiaoxiWin!.addComponent("OnBack");
        
        if(!cc.vv.userMgr.notice){
            cc.vv.userMgr.notice = {
                version:null,
                msg:"数据请求中...",
            }
        }
        
        if(!cc.vv.userMgr.gemstip){
            cc.vv.userMgr.gemstip = {
                version:null,
                msg:"数据请求中...",
            }
        }
        
        this.lblNotice!.string = cc.vv.userMgr.notice!.msg;
        
        this.refreshInfo();
        this.refreshNotice();
        this.refreshGemsTip();
        
        cc.vv.audioMgr.playBGM("bgMain.mp3");

        cc.vv.utils.addEscEvent(this.node);
    },
    
    refreshInfo:function(){
        var self = this;
        var onGet = function(this: HallSelf,ret: HttpResp){
            if(ret.errcode !== 0){
                console.log(ret.errmsg);
            }
            else{
                if(ret.gems != null){
                    // 老代码把数字直接赋给 `Label.string`（引擎的 setter 原样保存，渲染时自行转字符串），
                    // 这里只做可擦除的类型收口，赋值行为不变。
                    this.lblGems!.string = ret.gems as unknown as string;    
                }
            }
        };
        
        var data = {
            account:cc.vv.userMgr.account,
            sign:cc.vv.userMgr.sign,
        };
        cc.vv.http.sendRequest("/get_user_status",data,onGet.bind(this));
    },
    
    refreshGemsTip:function(){
        var self = this;
        var onGet = function(this: HallSelf,ret: HttpResp){
            if(ret.errcode !== 0){
                console.log(ret.errmsg);
            }
            else{
                // 网络边界：/get_message 在通用响应上多了 msg，按它的实际形状断言。
                var resp = ret as MessageResp;
                cc.vv.userMgr.gemstip!.version = resp.version;
                cc.vv.userMgr.gemstip!.msg = resp.msg.replace("<newline>","\n");
            }
        };
        
        var data = {
            account:cc.vv.userMgr.account,
            sign:cc.vv.userMgr.sign,
            type:"fkgm",
            version:cc.vv.userMgr.gemstip!.version
        };
        cc.vv.http.sendRequest("/get_message",data,onGet.bind(this));
    },
    
    refreshNotice:function(){
        var self = this;
        var onGet = function(this: HallSelf,ret: HttpResp){
            if(ret.errcode !== 0){
                console.log(ret.errmsg);
            }
            else{
                // 网络边界：/get_message 在通用响应上多了 msg，按它的实际形状断言。
                var resp = ret as MessageResp;
                cc.vv.userMgr.notice!.version = resp.version;
                cc.vv.userMgr.notice!.msg = resp.msg;
                this.lblNotice!.string = resp.msg;
            }
        };
        
        var data = {
            account:cc.vv.userMgr.account,
            sign:cc.vv.userMgr.sign,
            type:"notice",
            version:cc.vv.userMgr.notice!.version
        };
        cc.vv.http.sendRequest("/get_message",data,onGet.bind(this));
    },
    
    initButtonHandler:function(btnPath: string){
        var btn = cc.find(btnPath);
        cc.vv.utils.addClickEvent(btn,this.node,"Hall","onBtnClicked");        
    },
    
    
    
    initLabels:function(){
        // 老代码把 `string | null` 与数字直接赋给 `Label.string`（引擎的 setter 原样保存），
        // 这里只做可擦除的类型收口，赋值行为不变。
        this.lblName!.string = cc.vv.userMgr.userName!;
        this.lblMoney!.string = cc.vv.userMgr.coins as unknown as string;
        this.lblGems!.string = cc.vv.userMgr.gems as unknown as string;
        this.lblID!.string = "ID:" + cc.vv.userMgr.userId;
    },
    
    onBtnClicked:function(event: cc.Event){
        if(event.target.name == "btn_shezhi"){
            this.settingsWin!.active = true;
        }   
        else if(event.target.name == "btn_help"){
            this.helpWin!.active = true;
        }
        else if(event.target.name == "btn_xiaoxi"){
            this.xiaoxiWin!.active = true;
        }
        else if(event.target.name == "head"){
            cc.vv.userinfoShow.show(cc.vv.userMgr.userName!,cc.vv.userMgr.userId!,this.sprHeadImg!,cc.vv.userMgr.sex,cc.vv.userMgr.ip);
        }
    },
    
    onJoinGameClicked:function(){
        this.joinGameWin!.active = true;
    },
    
    onReturnGameClicked:function(){
        cc.vv.wc.show('正在返回游戏房间');
        cc.director.loadScene("mjgame");  
    },
    
    onBtnAddGemsClicked:function(){
        cc.vv.alert!.show("提示",cc.vv.userMgr.gemstip!.msg,function(this: HallSelf){
            this.onBtnTaobaoClicked();
        }.bind(this));
        this.refreshInfo();
    },
    
    onCreateRoomClicked:function(){
        if(cc.vv.gameNetMgr.roomId != null){
            cc.vv.alert!.show("提示","房间已经创建!\n必须解散当前房间才能创建新的房间");
            return;
        }
        console.log("onCreateRoomClicked");
        this.createRoomWin!.active = true;   
    },
    
    onBtnTaobaoClicked:function(){
        cc.sys.openURL('https://shop596732896.taobao.com/');
    },

    // called every frame, uncomment this function to activate update callback
    update: function (dt: number) {
        var x = this.lblNotice!.node.x;
        x -= dt*100;
        if(x + this.lblNotice!.node.width < -1000){
            x = 500;
        }
        this.lblNotice!.node.x = x;
        
        if(cc.vv && cc.vv.userMgr.roomData != null){
            cc.vv.userMgr.enterRoom(cc.vv.userMgr.roomData);
            cc.vv.userMgr.roomData = null;
        }
    },
});
export { };
