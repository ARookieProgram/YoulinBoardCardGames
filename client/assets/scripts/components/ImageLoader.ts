/** `cc.Rect` 在本工程里是不带 new 直接调用的（老代码写法），creator.d.ts 只把它声明成了类。 */
type RectCallable = (x: number, y: number, w: number, h: number) => cc.Rect;

/** `new cc.SpriteFrame(tex, rect)`：creator.d.ts 把构造签名写成了普通方法，new 时参数个数被判成 0。 */
interface SpriteFrameConstructor {
    new (filename?: string | cc.Texture2D, rect?: cc.Rect, rotated?: boolean, offset?: cc.Vec2, originalSize?: cc.Size): cc.SpriteFrame;
}

/** `/base_info` 的返回体；共享的 HttpResp 里没有声明这几个字段，这里补上本文件用到的形状。 */
interface BaseInfoResp {
    name: string;
    sex: number;
    headimgurl?: string | null;
}

function loadImage(url: string,code: number,callback: (code: number, spriteFrame: cc.SpriteFrame) => void){
    /*
    if(cc.vv.images == null){
        cc.vv.images = {};
    }
    var imageInfo = cc.vv.images[url];
    if(imageInfo == null){
        imageInfo = {
            image:null,
            queue:[],
        };
        cc.vv.images[url] = imageInfo;
    }
    
    cc.loader.load(url,function (err,tex) {
        imageInfo.image = tex;
        var spriteFrame = new cc.SpriteFrame(tex, cc.Rect(0, 0, tex.width, tex.height));
        for(var i = 0; i < imageInfo.queue.length; ++i){
            var itm = imageInfo.queue[i];
            itm.callback(itm.code,spriteFrame);
        }
        itm.queue = [];
    });
    if(imageInfo.image != null){
        var tex = imageInfo.image;
        var spriteFrame = new cc.SpriteFrame(tex, cc.Rect(0, 0, tex.width, tex.height));
        callback(code,spriteFrame);
    }
    else{
        imageInfo.queue.push({code:code,callback:callback});
    }*/
    // `cc.SpriteFrame` 与 `cc.Rect` 的调用方式与老代码完全一致，
    // 两处 as unknown as 只是给 creator.d.ts 漏掉/写错的签名补类型，运行期一字未改。
    cc.loader.load(url,function (err: Error | null,tex: cc.Texture2D) {
        var spriteFrame = new (cc.SpriteFrame as unknown as SpriteFrameConstructor)(tex, (cc.Rect as unknown as RectCallable)(0, 0, tex.width, tex.height));
        callback(code,spriteFrame);
    });
};

function getBaseInfo(userid: number,callback: (userid: number, info: UserBaseInfo) => void){
    if(cc.vv.baseInfoMap == null){
        cc.vv.baseInfoMap = {};
    }
    
    if(cc.vv.baseInfoMap[userid] != null){
        callback(userid,cc.vv.baseInfoMap[userid]);
    }
    else{
        cc.vv.http.sendRequest('/base_info',{userid:userid},function(ret){
            // 跨网络边界：按 /base_info 的实际返回形状断言（共享的 HttpResp 里没有 headimgurl）。
            var resp = ret as unknown as BaseInfoResp;
            var url: string | null = null;
            if(resp.headimgurl){
               url = cc.vv.http.master_url + '/image?url=' + encodeURIComponent(resp.headimgurl) + ".jpg";
            }
            var info = {
                name:resp.name,
                sex:resp.sex,
                url:url,
            }
            cc.vv.baseInfoMap![userid] = info;
            callback(userid,info);
            
        },cc.vv.http.master_url);   
    }  
};

const { ccclass } = cc._decorator;

@ccclass
export default class ImageLoader extends cc.Component {
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

    // 老代码里的 `_spriteFrame` 是运行时动态挂到实例上的，**不是 Creator 的序列化属性**。
    // 这里用 declare 只声明类型、不产生运行时代码：与「字段不存在」完全一致，没有补任何初始值。
    declare _spriteFrame: cc.SpriteFrame | undefined;

    // use this for initialization
    onLoad() {
        this.setupSpriteFrame();
    }

    setUserID(userid: number){
        if(!userid){
            return;
        }
        if(cc.vv.images == null){
            cc.vv.images = {};
        }
        
        var self = this;
        getBaseInfo(userid,function(code: number,info: UserBaseInfo){
           if(info && info.url){
                loadImage(info.url,userid,function (err,spriteFrame) {
                    self._spriteFrame = spriteFrame;
                    self.setupSpriteFrame();
                });   
            } 
        });
    }

    setupSpriteFrame(){
        if(this._spriteFrame){
            // creator.d.ts 里 cc.Component.getComponent 只返回 cc.Component，这里断言成实际取到的 cc.Sprite。
            var spr = this.getComponent(cc.Sprite) as cc.Sprite;
            if(spr){
                spr.spriteFrame = this._spriteFrame;    
            }
        }
    }
    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = ImageLoader;
