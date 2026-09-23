// 弹窗管理：设置面板与解散房间确认框。
//
// 本文件用 ES6 class + @ccclass/@property 装饰器（Creator 2.4 的官方写法）：
// 运行时行为与迁移前的 PopupMgr.js 完全一致，只补了类型标注、可空属性的 `!` 断言
// 与本地事件载荷的类型断言。

const { ccclass, property } = cc._decorator;

@ccclass
export default class PopupMgr extends cc.Component {
    // foo: {
    //    default: null,
    //    url: cc.Texture2D,  // optional, default is typeof default
    //    serializable: true, // optional, default is true
    //    visible: true,      // optional, default is true
    //    displayName: 'Foo', // optional
    //    readonly: false,    // optional, default is false
    // },
    // ...
    @property _popuproot: cc.Node | null = null;
    @property _settings: cc.Node | null = null;
    @property _dissolveNotice: cc.Node | null = null;

    @property _endTime: number = -1;
    // 运行期会被拼成一段多行文本，初值仍是 null（没有补初始值）。
    @property _extraInfo: string | null = null;
    @property _noticeLabel: cc.Label | null = null;

    // use this for initialization
    onLoad() {
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
    }

    start(){
        if(cc.vv.gameNetMgr.dissoveData){
            this.showDissolveNotice(cc.vv.gameNetMgr.dissoveData);
        }
    }

    addBtnHandler(btnName: string){
        var btn = cc.find("Canvas/popups/" + btnName);
        this.addClickEvent(btn,this.node,"PopupMgr","onBtnClicked");
    }

    addClickEvent(node: cc.Node,target: cc.Node,component: string,handler: string){
        var eventHandler = new cc.Component.EventHandler();
        eventHandler.target = target;
        eventHandler.component = component;
        eventHandler.handler = handler;

        var clickEvents = node.getComponent(cc.Button).clickEvents;
        clickEvents.push(eventHandler);
    }

    onBtnClicked(event: cc.Event){
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
    }

    closeAll(){
        this._popuproot!.active = false;
        this._settings!.active = false;
        this._dissolveNotice!.active = false;
    }

    showSettings(){
        this.closeAll();
        this._popuproot!.active = true;
        this._settings!.active = true;
    }

    showDissolveRequest(){
        this.closeAll();
        this._popuproot!.active = true;
    }

    showDissolveNotice(data: DissolveNoticePush){
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
    }

    
    // called every frame, uncomment this function to activate update callback
    update(dt: number = 0) {
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
    }
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = PopupMgr;
