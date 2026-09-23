const { ccclass, property } = cc._decorator;

@ccclass
export default class WaitingConnection extends cc.Component {
    // 老写法是简写 `target: cc.Node`（引擎规范化成 { default: null, type: cc.Node }）；
    // 这里写成 @property(cc.Node) 且初值为 null，序列化元数据与老代码一致。
    @property(cc.Node) target: cc.Node | null = null;
    // foo: {
    //    default: null,
    //    url: cc.Texture2D,  // optional, default is typeof default
    //    serializable: true, // optional, default is true
    //    visible: true,      // optional, default is true
    //    displayName: 'Foo', // optional
    //    readonly: false,    // optional, default is false
    // },
    // ...
    @property _isShow: boolean = false;
    @property(cc.Label) lblContent: cc.Label | null = null;

    // use this for initialization
    onLoad() {
        if(cc.vv == null){
            return null;
        }
        
        cc.vv.wc = this;
        this.node.active = this._isShow;
    }

    // called every frame, uncomment this function to activate update callback
    update(dt: number = 0) {
        this.target!.rotation = this.target!.rotation - dt*45;
    }

    show(content: string){
        this._isShow = true;
        if(this.node){
            this.node.active = this._isShow;   
        }
        if(this.lblContent){
            if(content == null){
                content = "";
            }
            this.lblContent.string = content;
        }
    }

    hide(){
        this._isShow = false;
        if(this.node){
            this.node.active = this._isShow;   
        }
    }
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = WaitingConnection;
