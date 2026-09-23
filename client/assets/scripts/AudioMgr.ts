const { ccclass, property } = cc._decorator;

@ccclass
export default class AudioMgr extends cc.Component {
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
    @property bgmVolume: number = 1.0;
    @property sfxVolume: number = 1.0;

    @property bgmAudioID: number = -1;

    /** 已加载的音频资源，key 是 `resources/sounds/` 下的相对路径（不带扩展名）。 */
    _clips: { [path: string]: cc.AudioClip } = {};

    /** 正在加载中的音频：同一段音频同时被请求多次时只发一次加载。 */
    _loading: { [path: string]: ((clip: cc.AudioClip) => void)[] } = {};

    /** 后台音乐的请求序号：切 BGM 时让还在加载中的旧请求作废。 */
    _bgmToken: number = 0;

    // use this for initialization
    init() {
        var t = cc.sys.localStorage.getItem("bgmVolume");
        if(t != null){
            this.bgmVolume = parseFloat(t);    
        }
        
        var t = cc.sys.localStorage.getItem("sfxVolume");
        if(t != null){
            this.sfxVolume = parseFloat(t);    
        }
        
        cc.game.on(cc.game.EVENT_HIDE, function () {
            console.log("cc.audioEngine.pauseAll");
            cc.audioEngine.pauseAll();
        });
        cc.game.on(cc.game.EVENT_SHOW, function () {
            console.log("cc.audioEngine.resumeAll");
            cc.audioEngine.resumeAll();
        });
    }

    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
    getUrl(url: string){
        return cc.url.raw("resources/sounds/" + url);
    }

    /** `cc.resources.load` 要的是不带扩展名的相对路径，例如 `sounds/bgMain`。 */
    getClipPath(url: string){
        return "sounds/" + url.replace(/\.(mp3|ogg|wav|m4a)$/i, "");
    }

    /**
     * 按需把 `resources/sounds/` 下的音频加载成 AudioClip 再回调。
     *
     * 老代码把 `cc.url.raw(...)` 得到的 **URL 字符串** 直接交给 `cc.audioEngine.play`，
     * 那是 Creator 1.x 的用法；2.4 的 `play` 要求 `clip instanceof cc.AudioClip`
     *（引擎 `cocos2d/audio/CCAudioEngine.js` 的 `play`，否则只打印
     * "Wrong type of AudioClip." 就返回），所以这里先把资源加载出来。
     * 同一个文件只加载一次，之后走缓存、回调是同步的。
     */
    getClip(url: string, callback: (clip: cc.AudioClip) => void){
        var path = this.getClipPath(url);
        var cached = this._clips[path];
        if(cached != null){
            callback(cached);
            return;
        }
        var waiting = this._loading[path];
        if(waiting != null){
            waiting.push(callback);
            return;
        }
        this._loading[path] = [callback];
        var self = this;
        cc.resources.load(path, cc.AudioClip, function(err: Error | null, clip: cc.AudioClip){
            var callbacks = self._loading[path];
            delete self._loading[path];
            if(err != null || clip == null){
                // 加载失败只丢掉这一段音频，不能顺带把正在播的 BGM 状态弄坏（老代码会把
                // undefined 赋给 bgmAudioID）。
                console.log("load audio failed:" + path + "," + err);
                return;
            }
            self._clips[path] = clip;
            for(var i = 0; i < callbacks.length; ++i){
                callbacks[i](clip);
            }
        });
    }

    playBGM(url: string){
        var self = this;
        var token = ++this._bgmToken;
        this.getClip(url, function(clip: cc.AudioClip){
            // 加载期间又切了别的 BGM：这次请求作废，免得后到的旧请求把新的顶掉。
            if(token !== self._bgmToken){
                return;
            }
            if(self.bgmAudioID >= 0){
                cc.audioEngine.stop(self.bgmAudioID);
            }
            self.bgmAudioID = cc.audioEngine.play(clip,true,self.bgmVolume);
        });
    }

    playSFX(url: string){
        if(this.sfxVolume <= 0){
            return;
        }
        var self = this;
        this.getClip(url, function(clip: cc.AudioClip){
            cc.audioEngine.play(clip,false,self.sfxVolume);
        });
    }

    setSFXVolume(v: number){
        if(this.sfxVolume != v){
            cc.sys.localStorage.setItem("sfxVolume",v);
            this.sfxVolume = v;
        }
    }

    setBGMVolume(v: number,force?: boolean){
        if(this.bgmAudioID >= 0){
            if(v > 0){
                cc.audioEngine.resume(this.bgmAudioID);
            }
            else{
                cc.audioEngine.pause(this.bgmAudioID);
            }
            //cc.audioEngine.setVolume(this.bgmAudioID,this.bgmVolume);
        }
        if(this.bgmVolume != v || force){
            cc.sys.localStorage.setItem("bgmVolume",v);
            this.bgmVolume = v;
            cc.audioEngine.setVolume(this.bgmAudioID,v);
        }
    }

    pauseAll(){
        cc.audioEngine.pauseAll();
    }

    resumeAll(){
        cc.audioEngine.resumeAll();
    }
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = AudioMgr;
