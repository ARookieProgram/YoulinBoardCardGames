/** `cc.vv.chat.getQuickChatInfo` 运行期返回的真实结构：Chat.js 里文案字段是 `content`，共享类型 QuickChatInfo 写成了 `text`。 */
interface QuickChatInfoRuntime extends QuickChatInfo {
    content: string;
    sound: string;
}

/** 运行期 `getComponent("Seat")` 取到的 Seat 组件（Seat.ts），这里只声明 MJRoom 用到的成员。 */
interface SeatApi extends cc.Component {
    setInfo(name: string, score: number | null, dayingjia?: boolean): void;
    setReady(isReady: boolean): void;
    setOffline(isOffline: boolean): void;
    setID(id: number): void;
    setZhuang(value: boolean): void;
    voiceMsg(show: boolean): void;
    refreshXuanPaiState(): void;
    chat(content: string): void;
    emoji(emoji: string): void;
}

const { ccclass, property } = cc._decorator;

@ccclass
export default class MJRoom extends cc.Component {
    @property({type: cc.Label}) lblRoomNo: cc.Label | null = null as cc.Label | null;
    // foo: {
    //    default: null,
    //    url: cc.Texture2D,  // optional, default is typeof default
    //    serializable: true, // optional, default is true
    //    visible: true,      // optional, default is true
    //    displayName: 'Foo', // optional
    //    readonly: false,    // optional, default is false
    // },
    // ...
    @property _seats: SeatApi[] = [];
    @property _seats2: SeatApi[] = [];
    @property _timeLabel: cc.Label | null = null;
    @property _voiceMsgQueue: ChatPush[] = [];
    @property _lastPlayingSeat: number | null = null;
    @property _playingSeat: number | null = null;
    @property _lastPlayTime: number | null = null;

    // 运行时动态字段（update 里才赋值），没有补初始值。
    declare _lastMinute: number | undefined;

    // use this for initialization
    onLoad() {
        if(cc.vv == null){
            return;
        }
        
        this.initView();
        this.initSeats();
        this.initEventHandlers();
    }

    initView(){
        var prepare = this.node.getChildByName("prepare");
        var seats = prepare.getChildByName("seats");
        for(var i = 0; i < seats.children.length; ++i){
            // getComponent 按类名取值在共享声明里返回 cc.Component，断言成 Seat 组件（运行期取到的就是它）。
            this._seats.push(seats.children[i].getComponent("Seat") as SeatApi);
        }
        
        this.refreshBtns();
        
        this.lblRoomNo = cc.find("Canvas/infobar/Z_room_txt/New Label").getComponent(cc.Label);
        this._timeLabel = cc.find("Canvas/infobar/time").getComponent(cc.Label);
        this.lblRoomNo!.string = cc.vv.gameNetMgr.roomId!;
        var gameChild = this.node.getChildByName("game");
        var sides = ["myself","right","up","left"];
        for(var i = 0; i < sides.length; ++i){
            var sideNode = gameChild.getChildByName(sides[i]);
            var seat = sideNode.getChildByName("seat");
            this._seats2.push(seat.getComponent("Seat") as SeatApi);
        }
        
        var btnWechat = cc.find("Canvas/prepare/btnWeichat");
        if(btnWechat){
            cc.vv.utils.addClickEvent(btnWechat,this.node,"MJRoom","onBtnWeichatClicked");
        }
        
        
        var titles = cc.find("Canvas/typeTitle");
        for(var i = 0; i < titles.children.length; ++i){
            titles.children[i].active = false;
        }
        
        if(cc.vv.gameNetMgr.conf){
            var type = cc.vv.gameNetMgr.conf.type;
            if(type == null || type == ""){
                type = "xzdd";
            }
            
            titles.getChildByName(type).active = true;   
        }
    }

    refreshBtns(){
        var prepare = this.node.getChildByName("prepare");
        var btnExit = prepare.getChildByName("btnExit");
        var btnDispress = prepare.getChildByName("btnDissolve");
        var btnWeichat = prepare.getChildByName("btnWeichat");
        var isIdle = cc.vv.gameNetMgr.numOfGames == 0;
        
        btnExit.active = !cc.vv.gameNetMgr.isOwner() && isIdle;
        btnDispress.active = cc.vv.gameNetMgr.isOwner() && isIdle;
        
        btnWeichat.active = isIdle;
    }

    initEventHandlers(){
        var self = this;
        this.node.on('new_user',function(data: SeatData){
            self.initSingleSeat(data);
        });
        
        this.node.on('user_state_changed',function(data: SeatData){
            self.initSingleSeat(data);
        });
        
        this.node.on('game_begin',function(data: unknown){
            self.refreshBtns();
            self.initSeats();
        });
        
        this.node.on('game_num',function(data: number){
            self.refreshBtns();
        });

        this.node.on('game_huanpai',function(data: unknown){
            // 老代码用 for...in 遍历数组，i 是字符串下标；这里只用一次断言说明类型，运行期取值不变。
            for(var i in self._seats2){
                self._seats2[i as unknown as number].refreshXuanPaiState();    
            }
        });
                
        this.node.on('huanpai_notify',function(data: SeatData){
            var idx = data.seatindex;
            var localIdx = cc.vv.gameNetMgr.getLocalIndex(idx);
            self._seats2[localIdx].refreshXuanPaiState();
        });
        
        this.node.on('game_huanpai_over',function(data: unknown){
            for(var i in self._seats2){
                self._seats2[i as unknown as number].refreshXuanPaiState();    
            }
        });
        
        this.node.on('voice_msg',function(data: ChatPush){
            self._voiceMsgQueue.push(data);
            self.playVoice();
        });
        
        this.node.on('chat_push',function(data: ChatPush){
            var idx = cc.vv.gameNetMgr.getSeatIndexByID(data.sender);
            var localIdx = cc.vv.gameNetMgr.getLocalIndex(idx);
            // 共享类型把 content 声明成 string | number，chat_push 的文案运行期是字符串。
            self._seats[localIdx].chat(data.content as string);
            self._seats2[localIdx].chat(data.content as string);
        });
        
        this.node.on('quick_chat_push',function(data: ChatPush){
            var idx = cc.vv.gameNetMgr.getSeatIndexByID(data.sender);
            var localIdx = cc.vv.gameNetMgr.getLocalIndex(idx);
            
            // quick_chat 的 content 是快捷语下标（共享类型写成 string | number）。
            var index = data.content as number;
            var info = cc.vv.chat.getQuickChatInfo(index) as QuickChatInfoRuntime;
            self._seats[localIdx].chat(info.content);
            self._seats2[localIdx].chat(info.content);
            
            cc.vv.audioMgr.playSFX(info.sound);
        });
        
        this.node.on('emoji_push',function(data: ChatPush){
            var idx = cc.vv.gameNetMgr.getSeatIndexByID(data.sender);
            var localIdx = cc.vv.gameNetMgr.getLocalIndex(idx);
            console.log(data);
            // emoji 的 content 是表情节点名（共享类型写成 string | number）。
            self._seats[localIdx].emoji(data.content as string);
            self._seats2[localIdx].emoji(data.content as string);
        });
    }

    initSeats(){
        var seats = cc.vv.gameNetMgr.seats!;
        for(var i = 0; i < seats.length; ++i){
            this.initSingleSeat(seats[i]);
        }
    }

    initSingleSeat(seat: SeatData){
        var index = cc.vv.gameNetMgr.getLocalIndex(seat.seatindex);
        var isOffline = !seat.online;
        var isZhuang = seat.seatindex == cc.vv.gameNetMgr.button;
        
        console.log("isOffline:" + isOffline);
        
        this._seats[index].setInfo(seat.name,seat.score);
        this._seats[index].setReady(seat.ready);
        this._seats[index].setOffline(isOffline);
        this._seats[index].setID(seat.userid);
        this._seats[index].voiceMsg(false);
        
        this._seats2[index].setInfo(seat.name,seat.score);
        this._seats2[index].setZhuang(isZhuang);
        this._seats2[index].setOffline(isOffline);
        this._seats2[index].setID(seat.userid);
        this._seats2[index].voiceMsg(false);
        this._seats2[index].refreshXuanPaiState();
    }

    onBtnSettingsClicked(){
        cc.vv.popupMgr.showSettings();   
    }

    onBtnBackClicked(){
        cc.vv.alert!.show("返回大厅","返回大厅房间仍会保留，快去邀请大伙来玩吧！",function(){
            cc.vv.wc.show('正在返回游戏大厅');
            cc.director.loadScene("hall");    
        },true);
    }

    onBtnChatClicked(){
        
    }

    onBtnWeichatClicked(){
        var title = "<血战到底>";
        if(cc.vv.gameNetMgr.conf!.type == "xlch"){
            var title = "<血流成河>";
        }
        cc.vv.anysdkMgr.share("天天麻将" + title,"房号:" + cc.vv.gameNetMgr.roomId! + " 玩法:" + cc.vv.gameNetMgr.getWanfa());
    }

    onBtnDissolveClicked(){
        cc.vv.alert!.show("解散房间","解散房间不扣房卡，是否确定解散？",function(){
            cc.vv.net.send("dispress");    
        },true);
    }

    onBtnExit(){
        cc.vv.net.send("exit");
    }

    playVoice(){
        if(this._playingSeat == null && this._voiceMsgQueue.length){
            console.log("playVoice2");
            var data = this._voiceMsgQueue.shift()!;
            var idx = cc.vv.gameNetMgr.getSeatIndexByID(data.sender);
            var localIndex = cc.vv.gameNetMgr.getLocalIndex(idx);
            this._playingSeat = localIndex;
            this._seats[localIndex].voiceMsg(true);
            this._seats2[localIndex].voiceMsg(true);
            
            // voice_msg 的 content 是 JSON 字符串（共享类型写成 string | number），parse 结果按 VoiceMsgContent 使用。
            var msgInfo = JSON.parse(data.content as string) as VoiceMsgContent;
            
            var msgfile = "voicemsg.amr";
            console.log(msgInfo.msg.length);
            cc.vv.voiceMgr.writeVoice(msgfile,msgInfo.msg);
            cc.vv.voiceMgr.play(msgfile);
            this._lastPlayTime = Date.now() + msgInfo.time;
        }
    }

    
    // called every frame, uncomment this function to activate update callback
    update(dt: number = 0) {
        var minutes = Math.floor(Date.now()/1000/60);
        if(this._lastMinute != minutes){
            this._lastMinute = minutes;
            var date = new Date();
            var h = date.getHours();
            // 老代码把 h 在数字与两位字符串之间复用，这里只对表达式做类型说明，运行期取值不变。
            h = (h < 10? "0"+h:h) as number;
            
            var m = date.getMinutes();
            m = (m < 10? "0"+m:m) as number;
            this._timeLabel!.string = "" + h + ":" + m;             
        }
        
        
        if(this._lastPlayTime != null){
            if(Date.now() > this._lastPlayTime + 200){
                this.onPlayerOver();
                this._lastPlayTime = null;    
            }
        }
        else{
            this.playVoice();
        }
    }

    onPlayerOver(){
        cc.vv.audioMgr.resumeAll();
        console.log("onPlayCallback:" + this._playingSeat);
        var localIndex = this._playingSeat;
        this._playingSeat = null;
        this._seats[localIndex!].voiceMsg(false);
        this._seats2[localIndex!].voiceMsg(false);
    }

    onDestroy(){
        cc.vv.voiceMgr.stop();
//        cc.vv.voiceMgr.onPlayCallback = null;
    }
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = MJRoom;
