cc.Class({
    extends: cc.Component,

    properties: {
        // foo: {
        //    default: null,
        //    url: cc.Texture2D,  // optional, default is typeof default
        //    serializable: true, // optional, default is true
        //    visible: true,      // optional, default is true
        //    displayName: 'Foo', // optional
        //    readonly: false,    // optional, default is false
        // },
        // ...
        // 这三项原来的值就是「类型」本身（运行期 Creator 读到的仍是构造函数），
        // 这里只加可擦除的断言把它标成实例类型，运行时行为不变。
        target:cc.Node as unknown as cc.Node | null,
        sprite:cc.SpriteFrame as unknown as cc.SpriteFrame | null,
        checkedSprite:cc.SpriteFrame as unknown as cc.SpriteFrame | null,
        checked:false,
        groupId:-1,
    },

    // use this for initialization
    onLoad: function () {
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
    },
    
    refresh:function(){
        var targetSprite = this.target!.getComponent(cc.Sprite);
        if(this.checked){
            targetSprite.spriteFrame = this.checkedSprite!;
        }
        else{
            targetSprite.spriteFrame = this.sprite!;
        }
    },
    
    check:function(value: boolean){
        this.checked = value;
        this.refresh();
    },
    
    onClicked:function(){
        // 同 onLoad：传进去的其实是本组件实例，共享接口把参数写成了 cc.Node。
        cc.vv.radiogroupmgr!.check(this as unknown as cc.Node);
    },

    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
    
    onDestroy:function(){
        if(cc.vv && cc.vv.radiogroupmgr){
            cc.vv.radiogroupmgr.del(this as unknown as cc.Node);            
        }
    }
});
export { };
