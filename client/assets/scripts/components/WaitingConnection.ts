cc.Class({
    extends: cc.Component,
    properties: {
        // 运行期 Creator 读到的仍是类型本身，这里只加可擦除的断言把它标成实例类型。
        target:cc.Node as unknown as cc.Node | null,
        // foo: {
        //    default: null,
        //    url: cc.Texture2D,  // optional, default is typeof default
        //    serializable: true, // optional, default is true
        //    visible: true,      // optional, default is true
        //    displayName: 'Foo', // optional
        //    readonly: false,    // optional, default is false
        // },
        // ...
        _isShow:false,
        lblContent:cc.Label as unknown as cc.Label | null,
    },

    // use this for initialization
    onLoad: function () {
        if(cc.vv == null){
            return null;
        }
        
        cc.vv.wc = this;
        this.node.active = this._isShow;
    },

    // called every frame, uncomment this function to activate update callback
    update: function (dt: number) {
        this.target!.rotation = this.target!.rotation - dt*45;
    },
    
    show:function(content: string){
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
    },
    hide:function(){
        this._isShow = false;
        if(this.node){
            this.node.active = this._isShow;   
        }
    }
});
export { };
