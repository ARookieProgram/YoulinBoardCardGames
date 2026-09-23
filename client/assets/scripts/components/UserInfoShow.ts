const { ccclass, property } = cc._decorator;

@ccclass
export default class UserInfoShow extends cc.Component {
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
    @property _userinfo: cc.Node | null = null;

    // use this for initialization
    onLoad() {
        if(cc.vv == null){
            return;
        }
        
        this._userinfo = cc.find("Canvas/userinfo");
        this._userinfo!.active = false;
        // 第 2 个参数运行期就是 this.node（Utils.js 直接把它赋给 eventHandler.target）。
        cc.vv.utils.addClickEvent(this._userinfo!,this.node,"UserInfoShow","onClicked");
        
        cc.vv.userinfoShow = this;
    }

    
    // 参数的顺序与含义沿用原实现：name, userId, iconSprite, sex, ip。
    show(name: string,userId: number,iconSprite: cc.Sprite,sex: number,ip: string){
        if(userId != null && userId > 0){
            this._userinfo!.active = true;
            this._userinfo!.getChildByName("icon").getComponent(cc.Sprite).spriteFrame = iconSprite.spriteFrame;
            this._userinfo!.getChildByName("name").getComponent(cc.Label).string = name;
            this._userinfo!.getChildByName("ip").getComponent(cc.Label).string = "IP: " + ip.replace("::ffff:","");
            this._userinfo!.getChildByName("id").getComponent(cc.Label).string = "ID: " + userId;
            
            var sex_female = this._userinfo!.getChildByName("sex_female");
            sex_female.active = false;
            
            var sex_male = this._userinfo!.getChildByName("sex_male");
            sex_male.active = false;
            
            if(sex == 1){
                sex_male.active = true;
            }   
            else if(sex == 2){
                sex_female.active = true;
            }
        }
    }

    onClicked(){
        this._userinfo!.active = false;
    }
    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = UserInfoShow;
