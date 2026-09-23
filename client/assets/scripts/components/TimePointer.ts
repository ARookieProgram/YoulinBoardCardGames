const { ccclass, property } = cc._decorator;

@ccclass
export default class TimePointer extends cc.Component {
    @property _arrow: cc.Node | null = null;
    @property _pointer: cc.Node | null = null;
    @property _timeLabel: cc.Label | null = null;
    @property _time: number = -1;
    @property _alertTime: number = -1;
    // foo: {
    //    default: null,
    //    url: cc.Texture2D,  // optional, default is typeof default
    //    serializable: true, // optional, default is true
    //    visible: true,      // optional, default is true
    //    displayName: 'Foo', // optional
    //    readonly: false,    // optional, default is false
    // },
    // ...

    // use this for initialization
    onLoad() {
        var gameChild = this.node.getChildByName("game");
        this._arrow = gameChild.getChildByName("arrow");
        this._pointer = this._arrow!.getChildByName("pointer");
        this.initPointer();
        
        this._timeLabel = this._arrow!.getChildByName("lblTime").getComponent(cc.Label);
        this._timeLabel.string = "00";
        
        var self = this;
        
        this.node.on('game_begin',function(data: unknown){
            self.initPointer();
        });
        
        this.node.on('game_chupai',function(data: unknown){
            self.initPointer();
            self._time = 10;
            self._alertTime = 3;
        });
    }

    initPointer(){
        if(cc.vv == null){
            return;
        }
        this._arrow!.active = cc.vv.gameNetMgr.gamestate == "playing";
        if(!this._arrow!.active){
            return;
        }
        var turn = cc.vv.gameNetMgr.turn;
        var localIndex = cc.vv.gameNetMgr.getLocalIndex(turn);
        for(var i = 0; i < this._pointer!.children.length; ++i){
            this._pointer!.children[i].active = i == localIndex;
        }
    }

    
    // called every frame, uncomment this function to activate update callback
    update(dt: number = 0) {
        if(this._time > 0){
            this._time -= dt;
            if(this._alertTime > 0 && this._time < this._alertTime){
                cc.vv.audioMgr.playSFX("timeup_alarm.mp3");
                this._alertTime = -1;
            }
            var pre = "";
            if(this._time < 0){
                this._time = 0;
            }
            
            var t = Math.ceil(this._time);
            if(t < 10){
                pre = "0";
            }
            this._timeLabel!.string = pre + t; 
        }
    }
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = TimePointer;
