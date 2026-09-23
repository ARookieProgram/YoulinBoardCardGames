/** `push_notice` 是 GameNetMgr.dispatchEvent 派发的本地事件，只有这两个字段。 */
interface NoticePush {
    time: number;
    info: string;
}

const { ccclass, property } = cc._decorator;

@ccclass
export default class NoticeTip extends cc.Component {
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
    @property _guohu: cc.Node | null = null;
    @property _info: cc.Label | null = null;
    @property _guohuTime: number = -1;

    // use this for initialization
    onLoad() {
        this._guohu = cc.find("Canvas/tip_notice");
        this._guohu!.active = false;
        
        this._info = cc.find("Canvas/tip_notice/info").getComponent(cc.Label);
        
        var self = this;
        this.node.on('push_notice',function(data: NoticePush){
            self._guohu!.active = true;
            self._guohuTime = data.time;
            self._info!.string = data.info;
        });
    }

    // called every frame, uncomment this function to activate update callback
    update(dt: number = 0) {
       if(this._guohuTime > 0){
           this._guohuTime -= dt;
           if(this._guohuTime < 0){
               this._guohu!.active = false;
           }
       }
    }
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = NoticeTip;
