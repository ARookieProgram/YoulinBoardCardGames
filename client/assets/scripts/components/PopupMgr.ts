// 弹窗管理：设置面板与解散房间确认框。
//
// 本文件是 ES5 风格（cc.Class / var / function）的 TypeScript 迁移产物：
// 运行时行为与迁移前的 PopupMgr.js 完全一致，只补了类型标注、可空属性的 `!` 断言
// 与本地事件载荷的类型断言。
cc.Class({
    extends: cc.Component,

    properties: {
        // foo: {
        //    default: null,
        //    url: cc.Texture2D,  // optional, default is typeof default
        //    serializable: true, // optional, default is true
        //    visible: true,      // optional, default is true
        //    displayName: 'Foo', // optional
        //    readonly: false,    // optional, default is false
        // },
        // ...
        _popuproot:null as cc.Node | null,
        _settings:null as cc.Node | null,
        _dissolveNotice:null as cc.Node | null,
        
        _endTime:-1,
        // 运行期会被拼成一段多行文本，初值仍是 null（没有补初始值）。
        _extraInfo:null as string | null,
        _noticeLabel:null as cc.Label | null,
    },

    // use this for initialization
    onLoad: function () {
        if(cc.vv == null){
            return;
        }
        
        cc.vv.popupMgr = this;
        
        this._popuproot = cc.find("Canvas/popups");
        this._settings = cc.find("Canvas/popups/settings");
        this._dissolveNotice = cc.find("Canvas/popups/dissolve_notice");
        this._noticeLabel = this._dissolveNotice.getChildByName("info").getComponent(cc.Label);
        
        this.closeAll();
        
        this.addBtnHandler("settings/btn_close");
        this.addBtnHandler("settings/btn_sqjsfj");
        this.addBtnHandler("dissolve_notice/btn_agree");
        this.addBtnHandler("dissolve_notice/btn_reject");
        this.addBtnHandler("dissolve_notice/btn_ok");
        
        var self = this;
        this.node.on("dissolve_notice",function(data){
            // 本地事件由 GameNetMgr.dispatchEvent 派发，载荷就是 dissolve_notice_push。
            self.showDissolveNotice(data as DissolveNoticePush);
        });
        
        this.node.on("dissolve_cancel",function(event){
            self.closeAll();
        });
    },
    
    start:function(){
        if(cc.vv.gameNetMgr.dissoveData){
            this.showDissolveNotice(cc.vv.gameNetMgr.dissoveData);
        }
    },
    
    addBtnHandler:function(btnName: string){
        var btn = cc.find("Canvas/popups/" + btnName);
        this.addClickEvent(btn,this.node,"PopupMgr","onBtnClicked");
    },
    
    addClickEvent:function(node: cc.Node,target: cc.Node,component: string,handler: string){
        var eventHandler = new cc.Component.EventHandler();
        eventHandler.target = target;
        eventHandler.component = component;
        eventHandler.handler = handler;

        var clickEvents = node.getComponent(cc.Button).clickEvents;
        clickEvents.push(eventHandler);
    },
    
    onBtnClicked:function(event: cc.Event){
        this.closeAll();
        var btnName = event.target.name;
        if(btnName == "btn_agree"){
            cc.vv.net.send("dissolve_agree");
        }
        else if(btnName == "btn_reject"){
            cc.vv.net.send("dissolve_reject");
        }
        else if(btnName == "btn_sqjsfj"){
            cc.vv.net.send("dissolve_request"); 
        }
    },
    
    closeAll:function(){
        this._popuproot!.active = false;
        this._settings!.active = false;
        this._dissolveNotice!.active = false;
    },
    
    showSettings:function(){
        this.closeAll();
        this._popuproot!.active = true;
        this._settings!.active = true;
    },
    
    showDissolveRequest:function(){
        this.closeAll();
        this._popuproot!.active = true;
    },
    
    showDissolveNotice:function(data: DissolveNoticePush){
        this._endTime = Date.now()/1000 + data.time;
        this._extraInfo = "";
        for(var i = 0; i < data.states.length; ++i){
            var b = data.states[i];
            var name = cc.vv.gameNetMgr.seats![i].name;
            if(b){
                this._extraInfo += "\n[已同意] "+ name;
            }
            else{
                this._extraInfo += "\n[待确认] "+ name;
            }
        }
        this.closeAll();
        this._popuproot!.active = true;
        this._dissolveNotice!.active = true;;
    },
    
    // called every frame, uncomment this function to activate update callback
    update: function (dt: number) {
        if(this._endTime > 0){
            var lastTime = this._endTime - Date.now() / 1000;
            if(lastTime < 0){
                this._endTime = -1;
            }
            
            var m = Math.floor(lastTime / 60);
            var s = Math.ceil(lastTime - m*60);
            
            var str = "";
            if(m > 0){
                str += m + "分"; 
            }
            
            this._noticeLabel!.string = str + s + "秒后房间将自动解散" + this._extraInfo;
        }
    },
});
export { };
