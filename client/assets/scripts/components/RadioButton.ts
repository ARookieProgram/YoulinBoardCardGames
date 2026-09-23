const { ccclass, property } = cc._decorator;

@ccclass
export default class RadioButton extends cc.Component {
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
    @property groupId: number = -1;

    // use this for initialization
    onLoad() {
        if(cc.vv == null){
            return;
        }
        if(cc.vv.radiogroupmgr == null){
            // require 是 Creator 的模块加载器（返回 unknown），这里断言成 RadioGroupMgr 的构造器。
            var RadioGroupMgr = require("RadioGroupMgr") as { new (): RadioGroupMgrApi };
            cc.vv.radiogroupmgr = new RadioGroupMgr();
            cc.vv.radiogroupmgr.init();
        }
        console.log(typeof(cc.vv.radiogroupmgr.add));
        // RadioGroupMgr 实际管理的就是 RadioButton 组件（共享接口里写成 cc.Node），断言只作用于类型。
        cc.vv.radiogroupmgr.add(this as unknown as cc.Node);

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

    check(value: boolean){
        this.checked = value;
        this.refresh();
    }

    onClicked(){
        // 同 onLoad：传进去的其实是本组件实例，共享接口把参数写成了 cc.Node。
        cc.vv.radiogroupmgr!.check(this as unknown as cc.Node);
    }

    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
    onDestroy(){
        if(cc.vv && cc.vv.radiogroupmgr){
            cc.vv.radiogroupmgr.del(this as unknown as cc.Node);            
        }
    }
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = RadioButton;
