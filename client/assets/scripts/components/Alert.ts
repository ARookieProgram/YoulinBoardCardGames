const { ccclass, property } = cc._decorator;

@ccclass
export default class Alert extends cc.Component {
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
    @property _alert: cc.Node | null = null;
    @property _btnOK: cc.Node | null = null;
    @property _btnCancel: cc.Node | null = null;
    @property _title: cc.Label | null = null;
    @property _content: cc.Label | null = null;
    @property _onok: (() => void) | null | undefined = null;

    // use this for initialization
    onLoad() {
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
    }

    onBtnClicked(event: cc.Event){
        if(event.target.name == "btn_ok"){
            if(this._onok){
                this._onok();
            }
        }
        this._alert!.active = false;
        this._onok = null;
    }

    
    // 后两个形参老代码里都不是必传的（调用方分别传 2 / 3 / 4 个），标成可选只是类型说明。
    show(title: string,content: string,onok?: (() => void) | null,needcancel?: boolean){
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
    }

    onDestory(){
        if(cc.vv){
            cc.vv.alert = null;    
        }
    }
    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = Alert;
