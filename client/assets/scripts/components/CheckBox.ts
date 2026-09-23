const { ccclass, property } = cc._decorator;

@ccclass
export default class CheckBox extends cc.Component {
    // foo: {
    //    default: null,
    //    url: cc.Texture2D,  // optional, default is typeof default
    //    serializable: true, // optional, default is true
    //    visible: true,      // optional, default is true
    //    displayName: 'Foo', // optional
    //    readonly: false,    // optional, default is false
    // },
    // ...
    // 老写法是简写（值就是类型构造器本身），引擎会规范化成 { default: null, type: X }；
    // 这里写成 @property(X) 且初值为 null，序列化元数据与老代码逐项一致
    //（见引擎 preprocess-class.js 的 getFullFormOfProperty）。
    @property(cc.Node) target: cc.Node | null = null;
    @property(cc.SpriteFrame) sprite: cc.SpriteFrame | null = null;
    @property(cc.SpriteFrame) checkedSprite: cc.SpriteFrame | null = null;
    @property checked: boolean = false;

    // use this for initialization
    onLoad() {
        this.refresh();
    }

    onClicked(){
        this.checked = !this.checked;
        this.refresh();
    }

    refresh(){
        var targetSprite = this.target!.getComponent(cc.Sprite);
        if(this.checked){
            targetSprite.spriteFrame = this.checkedSprite!;
        }
        else{
            targetSprite.spriteFrame = this.sprite!;
        }
    }
    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = CheckBox;
