// 老代码把 format 挂在 String 原型上；`this` 参数只是类型标注（可擦除），运行时签名不变。
// 声明写在 types/augment-F.d.ts 里（History.ts 也会调它，H 批次另有一份收 string|number 的声明）。
// 形参写成联合类型只是为了同时满足两份声明：对象参数走 key 替换，其余走 arguments 位置替换。
String.prototype.format = function(this: string, args: Record<string, string> | string | number) { 
    if (arguments.length>0) { 
        var result = this; 
        if (arguments.length == 1 && typeof (args) == "object") { 
            for (var key in args) { 
                var reg=new RegExp ("({"+key+"})","g"); 
                result = result.replace(reg, args[key]); 
            } 
        } 
        else { 
            for (var i = 0; i < arguments.length; i++) { 
                if(arguments[i]==undefined) { 
                    return ""; 
                } 
                else { 
                    var reg=new RegExp ("({["+i+"]})","g"); 
                    result = result.replace(reg, arguments[i]); 
                } 
            } 
        } 
        return result; 
    } 
    else { 
        return this; 
    } 
};
 
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
        _mima:null as string[] | null,
        _mimaIndex:0,
    },

    // use this for initialization
    onLoad: function () {
        cc.vv.utils.setFitSreenMode();
        cc.vv.http.url = cc.vv.http.master_url;
        cc.vv.net.addHandler('push_need_create_role',function(){
            console.log("onLoad:push_need_create_role");
            cc.director.loadScene("createrole");
        });
        
        cc.vv.audioMgr.playBGM("bgMain.mp3");
        
        this._mima = ["A","A","B","B","A","B","A","B","A","A","A","B","B","B"];
        
        if(!cc.sys.isNative || cc.sys.os == cc.sys.OS_WINDOWS){
            cc.find("Canvas/btn_yk").active = true;
            cc.find("Canvas/btn_weixin").active = false;
        }
        else{
            cc.find("Canvas/btn_yk").active = false;
            cc.find("Canvas/btn_weixin").active = true;
        }
    },
    
    start:function(){
        var account: string | null =  cc.sys.localStorage.getItem("wx_account");
        var sign: string | null = cc.sys.localStorage.getItem("wx_sign");
        if(account != null && sign != null && account != '' && sign != ''){
            var ret = {
                errcode:0,
                account:account,
                sign:sign
            }
            cc.vv.userMgr.onAuth(ret);
        }   
    },
    
    onBtnQuickStartClicked:function(){
        cc.vv.userMgr.guestAuth();
    },
    
    onBtnWeichatClicked:function(){
        var self = this;
        cc.vv.anysdkMgr.login();
    },
    
    onBtnMIMAClicked:function(event: cc.Event){
        if(this._mima![this._mimaIndex] == event.target.name){
            this._mimaIndex++;
            if(this._mimaIndex == this._mima!.length){
                cc.find("Canvas/btn_yk").active = true;
            }
        }
        else{
            console.log("oh ho~~~");
            this._mimaIndex = 0;
        }
    }

    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
});

export { };
