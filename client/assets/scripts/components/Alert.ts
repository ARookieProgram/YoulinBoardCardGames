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
        _alert:null as cc.Node | null,
        _btnOK:null as cc.Node | null,
        _btnCancel:null as cc.Node | null,
        _title:null as cc.Label | null,
        _content:null as cc.Label | null,
        _onok:null as (() => void) | null | undefined,
    },

    // use this for initialization
    onLoad: function () {
        if(cc.vv == null){
            return;
        }
        this._alert = cc.find("Canvas/alert");
        this._title = cc.find("Canvas/alert/title").getComponent(cc.Label);
        this._content = cc.find("Canvas/alert/content").getComponent(cc.Label);
        
        this._btnOK = cc.find("Canvas/alert/btn_ok");
        this._btnCancel = cc.find("Canvas/alert/btn_cancel");
        
        // 第 2 个参数运行期就是 this.node（Utils.js 直接把它赋给 eventHandler.target）。
        cc.vv.utils.addClickEvent(this._btnOK!,this.node,"Alert","onBtnClicked");
        cc.vv.utils.addClickEvent(this._btnCancel!,this.node,"Alert","onBtnClicked");
        
        this._alert!.active = false;
        cc.vv.alert = this;
    },
    
    onBtnClicked:function(event: cc.Event){
        if(event.target.name == "btn_ok"){
            if(this._onok){
                this._onok();
            }
        }
        this._alert!.active = false;
        this._onok = null;
    },
    
    // 后两个形参老代码里都不是必传的（调用方分别传 2 / 3 / 4 个），标成可选只是类型说明。
    show:function(title: string,content: string,onok?: (() => void) | null,needcancel?: boolean){
        this._alert!.active = true;
        this._onok = onok;
        this._title!.string = title;
        this._content!.string = content;
        if(needcancel){
            this._btnCancel!.active = true;
            this._btnOK!.x = -150;
            this._btnCancel!.x = 150;
        }
        else{
            this._btnCancel!.active = false;
            this._btnOK!.x = 0;
        }
    },
    
    onDestory:function(){
        if(cc.vv){
            cc.vv.alert = null;    
        }
    }

    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
});
export { };
