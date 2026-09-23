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
    },

    // use this for initialization
    onLoad: function () {
        this.refresh();
    },
    
    onClicked:function(){
        this.checked = !this.checked;
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
    }
    
    

    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
});
export { };
