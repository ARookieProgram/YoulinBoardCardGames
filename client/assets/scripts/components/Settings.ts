const { ccclass, property } = cc._decorator;

@ccclass
export default class Settings extends cc.Component {
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
    @property _btnYXOpen: cc.Node | null = null;
    @property _btnYXClose: cc.Node | null = null;
    @property _btnYYOpen: cc.Node | null = null;
    @property _btnYYClose: cc.Node | null = null;

    // use this for initialization
    onLoad() {
        if(cc.vv == null){
            return;
        }
                
        this._btnYXOpen = this.node.getChildByName("yinxiao").getChildByName("btn_yx_open");
        this._btnYXClose = this.node.getChildByName("yinxiao").getChildByName("btn_yx_close");
        
        this._btnYYOpen = this.node.getChildByName("yinyue").getChildByName("btn_yy_open");
        this._btnYYClose = this.node.getChildByName("yinyue").getChildByName("btn_yy_close");
        
        this.initButtonHandler(this.node.getChildByName("btn_close"));
        this.initButtonHandler(this.node.getChildByName("btn_exit"));
        
        
        this.initButtonHandler(this._btnYXOpen!);
        this.initButtonHandler(this._btnYXClose!);
        this.initButtonHandler(this._btnYYOpen!);
        this.initButtonHandler(this._btnYYClose!);
        

        var slider = this.node.getChildByName("yinxiao").getChildByName("progress");
        cc.vv.utils.addSlideEvent(slider,this.node,"Settings","onSlided");
        
        var slider = this.node.getChildByName("yinyue").getChildByName("progress");
        cc.vv.utils.addSlideEvent(slider,this.node,"Settings","onSlided");
        
        this.refreshVolume();
    }

    onSlided(slider: cc.Slider){
        if(slider.node.parent.name == "yinxiao"){
            cc.vv.audioMgr.setSFXVolume(slider.progress);
        }
        else if(slider.node.parent.name == "yinyue"){
            cc.vv.audioMgr.setBGMVolume(slider.progress);
        }
        this.refreshVolume();
    }

    initButtonHandler(btn: cc.Node){
        cc.vv.utils.addClickEvent(btn,this.node,"Settings","onBtnClicked");    
    }

    refreshVolume(){
        
        this._btnYXClose!.active = cc.vv.audioMgr.sfxVolume > 0;
        this._btnYXOpen!.active = !this._btnYXClose!.active;
        
        var yx = this.node.getChildByName("yinxiao");
        var width = 430 * cc.vv.audioMgr.sfxVolume;
        var progress = yx.getChildByName("progress")
        progress.getComponent(cc.Slider).progress = cc.vv.audioMgr.sfxVolume;
        progress.getChildByName("progress").width = width;  
        //yx.getChildByName("btn_progress").x = progress.x + width;
        
        
        this._btnYYClose!.active = cc.vv.audioMgr.bgmVolume > 0;
        this._btnYYOpen!.active = !this._btnYYClose!.active;
        var yy = this.node.getChildByName("yinyue");
        var width = 430 * cc.vv.audioMgr.bgmVolume;
        var progress = yy.getChildByName("progress");
        progress.getComponent(cc.Slider).progress = cc.vv.audioMgr.bgmVolume; 
        
        progress.getChildByName("progress").width = width;
        //yy.getChildByName("btn_progress").x = progress.x + width;
    }

    onBtnClicked(event: cc.Event){
        if(event.target.name == "btn_close"){
            this.node.active = false;
        }
        else if(event.target.name == "btn_exit"){
            cc.sys.localStorage.removeItem("wx_account");
            cc.sys.localStorage.removeItem("wx_sign");
            cc.director.loadScene("login");
        }
        else if(event.target.name == "btn_yx_open"){
            cc.vv.audioMgr.setSFXVolume(1.0);
            this.refreshVolume(); 
        }
        else if(event.target.name == "btn_yx_close"){
            cc.vv.audioMgr.setSFXVolume(0);
            this.refreshVolume();
        }
        else if(event.target.name == "btn_yy_open"){
            cc.vv.audioMgr.setBGMVolume(1);
            this.refreshVolume();
        }
        else if(event.target.name == "btn_yy_close"){
            cc.vv.audioMgr.setBGMVolume(0);
            this.refreshVolume();
        }
    }
    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = Settings;
