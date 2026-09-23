// 战绩列表与房间详情。
//
// 本文件用 ES6 class + @ccclass/@property 装饰器（Creator 2.4 的官方写法）：
// 运行时行为与迁移前的 History.js 完全一致，只补了类型标注与跨网络边界的断言。
//
// `get_detail_of_game` 的返回体里 `base_info` / `action_records` 在服务端是 JSON 字符串，
// 老代码拿到后原地 parse 再写回，所以下面用一个「解析前」的接口收口这个网络边界。
interface RawReplayDetail {
    base_info: string | BaseInfo;
    action_records: string | PaiList;
}

const { ccclass, property } = cc._decorator;

@ccclass
export default class History extends cc.Component {
    @property({type: cc.Prefab}) HistoryItemPrefab: cc.Prefab | null = null as cc.Prefab | null;
    // foo: {
    //    default: null,
    //    url: cc.Texture2D,  // optional, default is typeof default
    //    serializable: true, // optional, default is true
    //    visible: true,      // optional, default is true
    //    displayName: 'Foo', // optional
    //    readonly: false,    // optional, default is false
    // },
    // ...
    @property _history: cc.Node | null = null;
    @property _viewlist: cc.Node | null = null;
    @property _content: cc.Node | null = null;
    @property _viewitemTemp: cc.Node | null = null;
    @property _historyData: HistoryRoomInfo[] | null = null;
    @property _curRoomInfo: HistoryRoomInfo | null = null;
    @property _emptyTip: cc.Node | null = null;

    // use this for initialization
    onLoad() {
        this._history = this.node.getChildByName("history");
        this._history.active = false;
        
        this._emptyTip = this._history.getChildByName("emptyTip");
        this._emptyTip.active = true;
        
        this._viewlist = this._history.getChildByName("viewlist");
        this._content = cc.find("view/content",this._viewlist);
        
        this._viewitemTemp = this._content.children[0];
        this._content.removeChild(this._viewitemTemp);

        var node = cc.find("Canvas/btn_zhanji");        
        this.addClickEvent(node,this.node,"History","onBtnHistoryClicked");
        
        var node = cc.find("Canvas/history/btn_back");  
        this.addClickEvent(node,this.node,"History","onBtnBackClicked");
    }

    addClickEvent(node: cc.Node,target: cc.Node,component: string,handler: string){
        var eventHandler = new cc.Component.EventHandler();
        eventHandler.target = target;
        eventHandler.component = component;
        eventHandler.handler = handler;

        var clickEvents = node.getComponent(cc.Button).clickEvents;
        clickEvents.push(eventHandler);
    }

    onBtnBackClicked(){
        if(this._curRoomInfo == null){
            this._historyData = null;
            this._history!.active = false;            
        }
        else{
            this.initRoomHistoryList(this._historyData!);   
        }
    }

    onBtnHistoryClicked(){
        this._history!.active = true;
        var self = this;
        cc.vv.userMgr.getHistoryList(function(data){
            // 网络边界：回调拿到的是 ret.history，断言成房间战绩列表。
            var history = data as HistoryRoomInfo[];
            // 老代码的比较函数返回 boolean（运行时被当作 0/1 用），行为原样保留，只做类型收口。
            history.sort(function(a: HistoryRoomInfo,b: HistoryRoomInfo){
                return a.time < b.time; 
            } as unknown as (a: HistoryRoomInfo,b: HistoryRoomInfo) => number);
            self._historyData = history;
            for(var i = 0; i < history.length; ++i){
                for(var j = 0; j < 4; ++j){
                    var s = history[i].seats[j];
                    s.name = new Buffer(s.name,'base64').toString();
                }
            }
            self.initRoomHistoryList(history);
        });
    }

    dateFormat(time: number){
        var date = new Date(time);
        var datetime = "{0}-{1}-{2} {3}:{4}:{5}";
        var year = date.getFullYear();
        // 老代码会把 "0"+month 这类字符串写回同一个变量（拼出 "09"），所以按联合类型声明。
        var month: number | string = date.getMonth() + 1;
        month = month >= 10? month : ("0"+month);
        var day: number | string = date.getDate();
        day = day >= 10? day : ("0"+day);
        var h: number | string = date.getHours();
        h = h >= 10? h : ("0"+h);
        var m: number | string = date.getMinutes();
        m = m >= 10? m : ("0"+m);
        var s: number | string = date.getSeconds();
        s = s >= 10? s : ("0"+s);
        datetime = datetime.format(year,month,day,h,m,s);
        return datetime;
    }

    initRoomHistoryList(data: HistoryRoomInfo[]){
        for(var i = 0; i < data.length; ++i){
            var node = this.getViewItem(i);
            node.idx = i;
            var titleId = "" + (i + 1);
            node.getChildByName("title").getComponent(cc.Label).string = titleId;
            node.getChildByName("roomNo").getComponent(cc.Label).string = "房间ID:" + data[i].id;
            var datetime = this.dateFormat(data[i].time * 1000);
            node.getChildByName("time").getComponent(cc.Label).string = datetime;
            
            var btnOp = node.getChildByName("btnOp");
            btnOp.idx = i;
            btnOp.getChildByName("Label").getComponent(cc.Label).string = "详情";
            
            for(var j = 0; j < 4; ++j){
                var s = data[i].seats[j];
                var info = s.name + ":" +  s.score;
                //console.log(info);
                node.getChildByName("info" + j).getComponent(cc.Label).string = info;
            }
        }
        this._emptyTip!.active = data.length == 0;
        this.shrinkContent(data.length);
        this._curRoomInfo = null;
    }

    initGameHistoryList(roomInfo: HistoryRoomInfo,data: GameRecord[]){
        // 老代码的比较函数返回 boolean（运行时被当作 0/1 用），行为原样保留，只做类型收口。
        data.sort(function(a: GameRecord,b: GameRecord){
           return a.create_time < b.create_time; 
        } as unknown as (a: GameRecord,b: GameRecord) => number);
        for(var i = 0; i < data.length; ++i){
            var node = this.getViewItem(i);
            var idx = data.length - i - 1;
            node.idx = idx;
            var titleId = "" + (idx + 1);
            node.getChildByName("title").getComponent(cc.Label).string = titleId;
            node.getChildByName("roomNo").getComponent(cc.Label).string = "房间ID:" + roomInfo.id;
            var datetime = this.dateFormat(data[i].create_time * 1000);
            node.getChildByName("time").getComponent(cc.Label).string = datetime;
            
            var btnOp = node.getChildByName("btnOp");
            btnOp.idx = idx; 
            btnOp.getChildByName("Label").getComponent(cc.Label).string = "回放";
            
            var result = JSON.parse(data[i].result);
            for(var j = 0; j < 4; ++j){
                var s = roomInfo.seats[j];
                var info = s.name + ":" + result[j];
                //console.log(info);
                node.getChildByName("info" + j).getComponent(cc.Label).string = info;
            }
        }
        this.shrinkContent(data.length);
        this._curRoomInfo = roomInfo;
    }

    getViewItem(index: number): cc.Node{
        var content = this._content!;
        if(content.childrenCount > index){
            return content.children[index];
        }
        var node = cc.instantiate(this._viewitemTemp);
        content.addChild(node);
        return node;
    }

    shrinkContent(num: number){
        while(this._content!.childrenCount > num){
            var lastOne = this._content!.children[this._content!.childrenCount -1];
            this._content!.removeChild(lastOne,true);
        }
    }

    getGameListOfRoom(idx: number){
        var self = this;
        var roomInfo = this._historyData![idx];        
        cc.vv.userMgr.getGamesOfRoom(roomInfo.uuid,function(data){
            // 网络边界：回调拿到的是 ret.data，断言成单局战绩行列表。
            var records = data as GameRecord[];
            if(records != null && records.length > 0){
                self.initGameHistoryList(roomInfo,records);
            }
        });
    }

    getDetailOfGame(idx: number){
        var self = this;
        var roomUUID = this._curRoomInfo!.uuid;
        cc.vv.userMgr.getDetailOfGame(roomUUID,idx,function(data){
            // 网络边界：详情里的 base_info / action_records 是 JSON 字符串，parse 后写回原字段。
            var detail = data as RawReplayDetail;
            detail.base_info = JSON.parse(detail.base_info as string);
            detail.action_records = JSON.parse(detail.action_records as string);
            cc.vv.gameNetMgr.prepareReplay(self._curRoomInfo!,detail as ReplayDetail);
            cc.vv.replayMgr.init(detail as ReplayDetail);
            cc.director.loadScene("mjgame"); 
        });
    }

    onViewItemClicked(event: cc.Event){
        var idx = event.target.idx;
        console.log(idx);
        if(this._curRoomInfo == null){
            this.getGameListOfRoom(idx);
        }
        else{
            this.getDetailOfGame(idx);      
        }
    }

    onBtnOpClicked(event: cc.Event){
        var idx = event.target.parent.idx;
        console.log(idx);
        if(this._curRoomInfo == null){
            this.getGameListOfRoom(idx);
        }
        else{
            this.getDetailOfGame(idx);      
        }
    }
    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = History;
