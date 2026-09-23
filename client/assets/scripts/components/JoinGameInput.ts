/**
 * 组件实例上被嵌套回调用到的成员：包在 `.bind(this)` 里的 function 拿不到
 * 类方法的 `this` 类型，所以显式声明一个 this 类型。
 * `function (this: ...)` 是可擦除语法，运行时签名不变。
 */
interface JoinGameInputSelf extends cc.Component {
    nums: cc.Label[];
    _inputIndex: number;
    onResetClicked(): void;
}

const { ccclass, property } = cc._decorator;

@ccclass
export default class JoinGameInput extends cc.Component {
    @property({type: [cc.Label]}) nums: cc.Label[] = [] as cc.Label[];
    @property _inputIndex: number = 0;
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
        
    }

    onEnable(){
        this.onResetClicked();
    }

    onInputFinished(roomId: string){
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
    }

    onInput(num: number){
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
    }

    onN0Clicked(){
        this.onInput(0);  
    }

    onN1Clicked(){
        this.onInput(1);  
    }

    onN2Clicked(){
        this.onInput(2);
    }

    onN3Clicked(){
        this.onInput(3);
    }

    onN4Clicked(){
        this.onInput(4);
    }

    onN5Clicked(){
        this.onInput(5);
    }

    onN6Clicked(){
        this.onInput(6);
    }

    onN7Clicked(){
        this.onInput(7);
    }

    onN8Clicked(){
        this.onInput(8);
    }

    onN9Clicked(){
        this.onInput(9);
    }

    onResetClicked(){
        for(var i = 0; i < this.nums.length; ++i){
            this.nums[i].string = "";
        }
        this._inputIndex = 0;
    }

    onDelClicked(){
        if(this._inputIndex > 0){
            this._inputIndex -= 1;
            this.nums[this._inputIndex].string = "";
        }
    }

    onCloseClicked(){
        this.node.active = false;
    }

    parseRoomID(): string{
        var str = "";
        for(var i = 0; i < this.nums.length; ++i){
            str += this.nums[i].string;
        }
        return str;
    }
    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = JoinGameInput;
