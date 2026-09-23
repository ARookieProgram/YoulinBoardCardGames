const { ccclass } = cc._decorator;

@ccclass
export default class OnBack extends cc.Component {
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

    // use this for initialization
    onLoad() {
        var btn = this.node.getChildByName("btn_back");
        // 第 2 参就是 this.node：Utils.js 把它直接赋给 eventHandler.target。
        cc.vv.utils.addClickEvent(btn,this.node,"OnBack","onBtnClicked");        
    }

    onBtnClicked(event: cc.Event){
        if(event.target.name == "btn_back"){
            this.node.active = false;
        }
    }
    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = OnBack;
