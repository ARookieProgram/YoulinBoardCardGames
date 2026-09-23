const { ccclass, property } = cc._decorator;

@ccclass
export default class ReplayCtrl extends cc.Component {
    // foo: {
    //    default: null,
    //    url: cc.Texture2D,  // optional, default is typeof default
    //    serializable: true, // optional, default is true
    //    visible: true,      // optional, default is true
    //    displayName: 'Foo', // optional
    //    readonly: false,    // optional, default is false
    // },
    // ...
    @property _nextPlayTime: number = 1;
    @property _replay: cc.Node | null = null;
    @property _isPlaying: boolean = true;

    // use this for initialization
    onLoad() {
        if(cc.vv == null){
            return;
        }
        
        this._replay = cc.find("Canvas/replay");
        this._replay!.active = cc.vv.replayMgr.isReplay();
    }

    onBtnPauseClicked(){
        this._isPlaying = false;
    }

    onBtnPlayClicked(){
        this._isPlaying = true;
    }

    onBtnBackClicked(){
        cc.vv.replayMgr.clear();
        cc.vv.gameNetMgr.reset();
        cc.vv.gameNetMgr.roomId = null;
        cc.vv.wc.show('正在返回游戏大厅');
        cc.director.loadScene("hall");
    }

    // called every frame, uncomment this function to activate update callback
    update(dt: number = 0) {
        if(cc.vv){
            if(this._isPlaying && cc.vv.replayMgr.isReplay() == true && this._nextPlayTime > 0){
                this._nextPlayTime -= dt;
                if(this._nextPlayTime < 0){
                    this._nextPlayTime = cc.vv.replayMgr.takeAction();
                }
            }
        }
    }
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = ReplayCtrl;
