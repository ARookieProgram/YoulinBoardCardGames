/**
 * 组件实例上被嵌套回调用到的成员：cc.Class 的 ThisType 只作用于 options 对象本身，
 * 包在 `.bind(this)` 里的 function 拿不到它，所以显式声明一个 this 类型。
 * `function (this: ...)` 是可擦除语法，运行时签名不变。
 */
interface JoinGameInputSelf extends cc.Component {
    nums: cc.Label[];
    _inputIndex: number;
    onResetClicked(): void;
}

cc.Class({
    extends: cc.Component,

    properties: {
        nums:{
            default:[] as cc.Label[],
            type:[cc.Label]
        },
        _inputIndex:0,
        // foo: {
        //    default: null,
        //    url: cc.Texture2D,  // optional, default is typeof default
        //    serializable: true, // optional, default is true
        //    visible: true,      // optional, default is true
        //    displayName: 'Foo', // optional
        //    readonly: false,    // optional, default is false
        // },
        // ...
    },

    // use this for initialization
    onLoad: function () {
        
    },
    
    onEnable:function(){
        this.onResetClicked();
    },
    
    onInputFinished:function(roomId: string){
        cc.vv.userMgr.enterRoom(roomId,function(this: JoinGameInputSelf, ret: HttpResp){
            if(ret.errcode == 0){
                this.node.active = false;
            }
            else{
                var content = "房间["+ roomId +"]不存在，请重新输入!";
                if(ret.errcode == 4){
                    content = "房间["+ roomId + "]已满!";
                }
                cc.vv.alert!.show("提示",content);
                this.onResetClicked();
            }
        }.bind(this)); 
    },
    
    onInput:function(num: number){
        if(this._inputIndex >= this.nums.length){
            return;
        }
        // 老代码就是把这个 0~9 的数字直接塞进 Label.string（引擎照 string 用），断言只影响类型，值不变。
        this.nums[this._inputIndex].string = num as unknown as string;
        this._inputIndex += 1;
        
        if(this._inputIndex == this.nums.length){
            var roomId = this.parseRoomID();
            console.log("ok:" + roomId);
            this.onInputFinished(roomId);
        }
    },
    
    onN0Clicked:function(){
        this.onInput(0);  
    },
    onN1Clicked:function(){
        this.onInput(1);  
    },
    onN2Clicked:function(){
        this.onInput(2);
    },
    onN3Clicked:function(){
        this.onInput(3);
    },
    onN4Clicked:function(){
        this.onInput(4);
    },
    onN5Clicked:function(){
        this.onInput(5);
    },
    onN6Clicked:function(){
        this.onInput(6);
    },
    onN7Clicked:function(){
        this.onInput(7);
    },
    onN8Clicked:function(){
        this.onInput(8);
    },
    onN9Clicked:function(){
        this.onInput(9);
    },
    onResetClicked:function(){
        for(var i = 0; i < this.nums.length; ++i){
            this.nums[i].string = "";
        }
        this._inputIndex = 0;
    },
    onDelClicked:function(){
        if(this._inputIndex > 0){
            this._inputIndex -= 1;
            this.nums[this._inputIndex].string = "";
        }
    },
    onCloseClicked:function(){
        this.node.active = false;
    },
    
    parseRoomID:function(): string{
        var str = "";
        for(var i = 0; i < this.nums.length; ++i){
            str += this.nums[i].string;
        }
        return str;
    }

    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
});

export { };
