if(cc.sys.isNative){
    jsb.reflection.callStaticMethod = function(){
        
    }
}

const { ccclass, property } = cc._decorator;

@ccclass
export default class AnysdkMgr extends cc.Component {
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
    // 标注 boolean 而不是让初值 `false` 推定成字面量类型，否则与 shareResult 里的
    // `this._isCapturing = true` 及 AnysdkMgr 接口冲突
    @property _isCapturing: boolean = false;

    // 以下字段老代码是运行时动态挂到实例上的，**不是 Creator 的序列化属性**。
    // 这里用 declare 只声明类型、不产生运行时代码：与「字段不存在」完全一致，没有补任何初始值。
    declare ANDROID_API: string | undefined;
    declare IOS_API: string | undefined;

    // use this for initialization
    onLoad() {
    }

    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
    init(){
        this.ANDROID_API = "com/babykylin/NativeAPI";
        this.IOS_API = "AppController";
    }

    getBatteryPercent(): number{
        if(cc.sys.isNative){
            if(cc.sys.os == cc.sys.OS_ANDROID){
                // jsb 反射调用是动态边界，按原生约定断言成 number
                return jsb.reflection.callStaticMethod(this.ANDROID_API, "getBatteryPercent", "()F") as number;
            }
            else if(cc.sys.os == cc.sys.OS_IOS){
                return jsb.reflection.callStaticMethod(this.IOS_API, "getBatteryPercent") as number;
            }            
        }
        return 0.9;
    }

    login(){
        if(cc.sys.os == cc.sys.OS_ANDROID){ 
            jsb.reflection.callStaticMethod(this.ANDROID_API, "Login", "()V");
        }
        else if(cc.sys.os == cc.sys.OS_IOS){
            jsb.reflection.callStaticMethod(this.IOS_API, "login");
        }
        else{
            console.log("platform:" + cc.sys.os + " dosn't implement share.");
        }
    }

    share(title: string,desc: string){
        if(cc.sys.os == cc.sys.OS_ANDROID){
            jsb.reflection.callStaticMethod(this.ANDROID_API, "Share", "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V",cc.vv.SI.appweb,title,desc);
        }
        else if(cc.sys.os == cc.sys.OS_IOS){
            jsb.reflection.callStaticMethod(this.IOS_API, "share:shareTitle:shareDesc:",cc.vv.SI.appweb,title,desc);
        }
        else{
            console.log("platform:" + cc.sys.os + " dosn't implement share.");
        }
    }

    shareResult(){
        if(this._isCapturing){
            return;
        }
        this._isCapturing = true;
        var size = cc.director.getWinSize();
        var currentDate = new Date();
        var fileName = "result_share.jpg";
        var fullPath = jsb.fileUtils.getWritablePath() + fileName;
        if(jsb.fileUtils.isFileExist(fullPath)){
            jsb.fileUtils.removeFile(fullPath);
        }
        var texture = new cc.RenderTexture(Math.floor(size.width), Math.floor(size.height));
        texture.setPosition(cc.p(size.width/2, size.height/2));
        texture.begin();
        cc.director.getRunningScene().visit();
        texture.end();
        texture.saveToFile(fileName, cc.IMAGE_FORMAT_JPG);
        
        var self = this;
        var tryTimes = 0;
        var fn = function(){
            if(jsb.fileUtils.isFileExist(fullPath)){
                var height = 100;
                var scale = height/size.height;
			    var width = Math.floor(size.width * scale);
                
                if(cc.sys.os == cc.sys.OS_ANDROID){
                    jsb.reflection.callStaticMethod(self.ANDROID_API, "ShareIMG", "(Ljava/lang/String;II)V",fullPath,width,height);
                }
                else if(cc.sys.os == cc.sys.OS_IOS){
                    jsb.reflection.callStaticMethod(self.IOS_API, "shareIMG:width:height:",fullPath,width,height);
                }
                else{
                    console.log("platform:" + cc.sys.os + " dosn't implement share.");
                }
                self._isCapturing = false;
            }
            else{
                tryTimes++;
                if(tryTimes > 10){
                    console.log("time out...");
                    return;
                }
                setTimeout(fn,50); 
            }
        }
        setTimeout(fn,50);
    }

    onLoginResp(code: unknown){
        var fn = function(ret: HttpResp){
            if(ret.errcode == 0){
                cc.sys.localStorage.setItem("wx_account",ret.account!);
                cc.sys.localStorage.setItem("wx_sign",ret.sign!);
            }
            cc.vv.userMgr.onAuth(ret);
        }
        cc.vv.http.sendRequest("/wechat_auth",{code:code,os:cc.sys.os},fn);
    }
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = AnysdkMgr;
