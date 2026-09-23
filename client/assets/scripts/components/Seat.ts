/** ImageLoader 组件（ImageLoader.js）在本文件用到的成员：`getComponent("ImageLoader")` 运行期取到的就是它。 */
interface ImageLoaderComponent extends cc.Component {
    setUserID(userid: number): void;
}

cc.Class({
    extends: cc.Component,

    properties: {
        _sprIcon:null as ImageLoaderComponent | null,
        _zhuang:null as cc.Node | null,
        _ready:null as cc.Node | null,
        _offline:null as cc.Node | null,
        _lblName:null as cc.Label | null,
        _lblScore:null as cc.Label | null,
        _scoreBg:null as cc.Node | null,
        _nddayingjia:null as cc.Node | null,
        _voicemsg:null as cc.Node | null,
        
        _chatBubble:null as cc.Node | null,
        _emoji:null as cc.Node | null,
        _lastChatTime:-1,
        
        _userName:"",
        // setInfo 会先把可能为 null 的 score 赋进来，再判空兜底成 0，所以这里允许 null。
        _score:0 as number | null,
        // setInfo 的第 3 个参数老代码可以不传（MJRoom 只传两个），运行期可能是 undefined。
        _dayingjia:false as boolean | undefined,
        _isOffline:false,
        _isReady:false,
        _isZhuang:false,
        _userId:null as number | null,
    },

    // 运行时动态字段（onLoad 里才赋值），没有补初始值。
    _xuanpai: undefined as cc.Node | undefined,

    // use this for initialization
    onLoad: function () {
        if(cc.vv == null){
            return;
        }
        
        // getComponent 按类名取值的返回值在共享声明里是 cc.Component，这里断言成 ImageLoader 组件，只为能调 setUserID。
        this._sprIcon = this.node.getChildByName("icon").getComponent("ImageLoader") as ImageLoaderComponent;
        this._lblName = this.node.getChildByName("name").getComponent(cc.Label);
        this._lblScore = this.node.getChildByName("score").getComponent(cc.Label);
        this._voicemsg = this.node.getChildByName("voicemsg");
        this._xuanpai = this.node.getChildByName("xuanpai");
        this.refreshXuanPaiState();
        
        if(this._voicemsg){
            this._voicemsg.active = false;
        }
        
        if(this._sprIcon && this._sprIcon.getComponent(cc.Button)){
            // 共享声明把 addClickEvent 的第 1 参写成 cc.Node，老代码传进来的其实是 ImageLoader 组件
            //（Utils.ts 里对它调 getComponent，运行期取到的按钮与传 node 时一致），这里只做类型断言。
            cc.vv.utils.addClickEvent(this._sprIcon as unknown as cc.Node,this.node,"Seat","onIconClicked");    
        }
        
        
        this._offline = this.node.getChildByName("offline");
        
        this._ready = this.node.getChildByName("ready");
        
        this._zhuang = this.node.getChildByName("zhuang");
        
        this._scoreBg = this.node.getChildByName("Z_money_frame");
        this._nddayingjia = this.node.getChildByName("dayingjia");
        
        this._chatBubble = this.node.getChildByName("ChatBubble");
        if(this._chatBubble != null){
            this._chatBubble.active = false;            
        }
        
        this._emoji = this.node.getChildByName("emoji");
        if(this._emoji != null){
            this._emoji.active = false;
        }
        
        this.refresh();
        
        if(this._sprIcon && this._userId){
            this._sprIcon.setUserID(this._userId);
        }
    },
    
    onIconClicked:function(){
        var iconSprite = this._sprIcon!.node.getComponent(cc.Sprite);
        if(this._userId != null && this._userId > 0){
           var seat = cc.vv.gameNetMgr.getSeatByID(this._userId);
            var sex = 0;
            if(cc.vv.baseInfoMap){
                var info = cc.vv.baseInfoMap[this._userId];
                if(info){
                    sex = info.sex;
                }                
            }
            cc.vv.userinfoShow.show(seat.name,seat.userid,iconSprite,sex,seat.ip);         
        }
    },
    
    refresh:function(){
        if(this._lblName != null){
            this._lblName.string = this._userName;    
        }
        
        if(this._lblScore != null){
            // 老代码把数字 _score 直接赋给 Label.string，运行期由引擎做隐式转换；这里只做类型说明。
            this._lblScore.string = this._score as unknown as string;            
        }        
        
        if(this._nddayingjia != null){
            this._nddayingjia.active = this._dayingjia == true;
        }
        
        if(this._offline){
            this._offline.active = this._isOffline && this._userName != "";
        }
        
        if(this._ready){
            this._ready.active = this._isReady && (cc.vv.gameNetMgr.numOfGames > 0); 
        }
        
        if(this._zhuang){
            this._zhuang.active = this._isZhuang;    
        }
        
        this.node.active = this._userName != null && this._userName != ""; 
    },
    
    setInfo(name: string,score: number | null,dayingjia?: boolean){
        this._userName = name;
        this._score = score;
        if(this._score == null){
            this._score = 0;
        }
        this._dayingjia = dayingjia;
        
        if(this._scoreBg != null){
            this._scoreBg.active = this._score != null;            
        }

        if(this._lblScore != null){
            this._lblScore.node.active = this._score != null;            
        }

        this.refresh();    
    },
    
    setZhuang:function(value: boolean){
        this._isZhuang = value;
        if(this._zhuang){
            this._zhuang.active = value;
        }
    },
    
    setReady:function(isReady: boolean){
        this._isReady = isReady;
        if(this._ready){
            this._ready.active = this._isReady && (cc.vv.gameNetMgr.numOfGames > 0); 
        }
    },
    
    setID:function(id: number){
        var idNode = this.node.getChildByName("id");
        if(idNode){
            var lbl = idNode.getComponent(cc.Label);
            lbl.string = "ID:" + id;            
        }
        
        this._userId = id;
        if(this._sprIcon){
            this._sprIcon.setUserID(id); 
        }
    },
    
    setOffline:function(isOffline: boolean){
        this._isOffline = isOffline;
        if(this._offline){
            this._offline.active = this._isOffline && this._userName != "";
        }
    },
    
    chat:function(content: string){
        if(this._chatBubble == null || this._emoji == null){
            return;
        }
        this._emoji.active = false;
        this._chatBubble.active = true;
        this._chatBubble.getComponent(cc.Label).string = content;
        this._chatBubble.getChildByName("New Label").getComponent(cc.Label).string = content;
        this._lastChatTime = 3;
    },
    
    emoji:function(emoji: string){
        //emoji = JSON.parse(emoji);
        if(this._emoji == null || this._emoji == null){
            return;
        }
        console.log(emoji);
        this._chatBubble!.active = false;
        this._emoji.active = true;
        this._emoji.getComponent(cc.Animation).play(emoji);
        this._lastChatTime = 3;
    },
    
    voiceMsg:function(show: boolean){
        if(this._voicemsg){
            this._voicemsg.active = show;
        }
    },
    
    refreshXuanPaiState:function(){
        if(this._xuanpai == null){
            return;
        }
        
        this._xuanpai.active = cc.vv.gameNetMgr.isHuanSanZhang;
        if(cc.vv.gameNetMgr.isHuanSanZhang == false){ 
            return;
        }
       
        this._xuanpai.getChildByName("xz").active = false;
        this._xuanpai.getChildByName("xd").active = false;
        
        var seat = cc.vv.gameNetMgr.getSeatByID(this._userId!);
        if(seat){
            if(seat.huanpais == null){
                this._xuanpai.getChildByName("xz").active = true;
            }
            else{
                this._xuanpai.getChildByName("xd").active = true;
            }
        }
    },
   
    // called every frame, uncomment this function to activate update callback
    update: function (dt: number) {
        if(this._lastChatTime > 0){
            this._lastChatTime -= dt;
            if(this._lastChatTime < 0){
                this._chatBubble!.active = false;
                this._emoji!.active = false;
                this._emoji!.getComponent(cc.Animation).stop();
            }
        }
    },
});

export { };
