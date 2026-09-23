// 结算面板：单局结束（game_over）与总结算的展示逻辑。
//
// 本文件用 ES6 class + @ccclass/@property 装饰器（Creator 2.4 的官方写法）：
// 运行时行为与迁移前的 GameOver.js 完全一致，只补了类型标注与本地事件载荷的断言。
// `game_over` 是 GameNetMgr 用 `dispatchEvent` 派发的本地事件，载荷就是 results 数组。

/** 单个座位的结算视图：`onLoad` 里按场景节点现搭出来的本地结构，不是序列化字段。 */
interface GameOverSeatView {
    username: cc.Label;
    reason: cc.Label;
    /** 只有场景里存在名为 "fan" 的子节点时才会挂上（老代码的原样判断）。 */
    fan?: cc.Label;
    score: cc.Label;
    hu: cc.Node;
    mahjongs: cc.Node;
    zhuang: cc.Node;
    hupai: cc.Node;
    _pengandgang: cc.Node[];
}

/**
 * xlch 的 huinfo 元素：沿用 domain.d.ts 的 HuInfoItem。
 * 老代码在结算面板里读的是 `haidihu` / `tianhu` / `dihu`，而服务端写进 huinfo 的字段名其实是
 * `isHaiDiHu` / `isTianHu` / `isDiHu`（domain.d.ts 记录的就是后者），所以这三个判断运行期恒为假。
 * 这里只在类型层面补上老代码读的字段名，不做修正、行为不变。
 */
interface GameOverHuInfo extends HuInfoItem {
    haidihu?: boolean;
    tianhu?: boolean;
    dihu?: boolean;
}

/**
 * 结算数据：沿用 domain.d.ts 的 GameResultSeat。
 * 老代码还会读 `dingque`，但服务端的 UserResult 并不下发这个字段（运行期取到的是 undefined），
 * 这里只在类型层面把它补上，运行行为不变。
 */
interface GameOverResultSeat extends GameResultSeat {
    dingque: number | undefined;
    /** 本文件的 xlch 分支按 `GameOverHuInfo` 读 huinfo（见上面的说明）。 */
    huinfo?: GameOverHuInfo[];
}

const { ccclass, property } = cc._decorator;

@ccclass
export default class GameOver extends cc.Component {
    // foo: {
    //    default: null,
    //    url: cc.Texture2D,  // optional, default is typeof default
    //    serializable: true, // optional, default is true
    //    visible: true,      // optional, default is true
    //    displayName: 'Foo', // optional
    //    readonly: false,    // optional, default is false
    // },
    // ...
    @property _gameover: cc.Node | null = null;
    @property _gameresult: cc.Node | null = null;
    @property _seats: GameOverSeatView[] = [];
    @property _isGameEnd: boolean = false;
    @property _pingju: cc.Node | null = null;
    @property _win: cc.Node | null = null;
    @property _lose: cc.Node | null = null;

    // use this for initialization
    onLoad() {
        if(cc.vv == null){
            return;
        }
        if(cc.vv.gameNetMgr.conf == null){
            return;
        }
        if(cc.vv.gameNetMgr.conf.type == "xzdd"){
            this._gameover = this.node.getChildByName("game_over");
        }
        else{
            this._gameover = this.node.getChildByName("game_over_xlch");
        }
        
        this._gameover.active = false;
        
        this._pingju = this._gameover.getChildByName("pingju");
        this._win = this._gameover.getChildByName("win");
        this._lose = this._gameover.getChildByName("lose");
        
        this._gameresult = this.node.getChildByName("game_result");
        
        var wanfa = this._gameover.getChildByName("wanfa").getComponent(cc.Label);
        wanfa.string = cc.vv.gameNetMgr.getWanfa();
        
        var listRoot = this._gameover.getChildByName("result_list");
        for(var i = 1; i <= 4; ++i){
            var s = "s" + i;
            var sn = listRoot.getChildByName(s);
            var viewdata = {} as GameOverSeatView;
            viewdata.username = sn.getChildByName('username').getComponent(cc.Label);
            viewdata.reason = sn.getChildByName('reason').getComponent(cc.Label);
            
            var f = sn.getChildByName('fan');
            if(f != null){
                viewdata.fan = f.getComponent(cc.Label);    
            }
            
            viewdata.score = sn.getChildByName('score').getComponent(cc.Label);
            viewdata.hu = sn.getChildByName('hu');
            viewdata.mahjongs = sn.getChildByName('pai');
            viewdata.zhuang = sn.getChildByName('zhuang');
            viewdata.hupai = sn.getChildByName('hupai');
            viewdata._pengandgang = [];
            this._seats.push(viewdata);
        }
        
        //初始化网络事件监听器
        var self = this;
        // game_over 派发的就是结算数组（GameNetMgr 里传的 results）。
        this.node.on('game_over',function(data){self.onGameOver(data as GameOverResultSeat[]);});
        
        this.node.on('game_end',function(data){self._isGameEnd = true;});
    }

    onGameOver(data: GameOverResultSeat[]){
        if(cc.vv.gameNetMgr.conf!.type == "xzdd"){
            this.onGameOver_XZDD(data);
        }
        else{
            this.onGameOver_XLCH(data);
        }
    }

    onGameOver_XZDD(data: GameOverResultSeat[]){
        console.log(data);
        if(data.length == 0){
            this._gameresult!.active = true;
            return;
        }
        this._gameover!.active = true;
        this._pingju!.active = false;
        this._win!.active = false;
        this._lose!.active = false;

        var myscore = data[cc.vv.gameNetMgr.seatIndex].score;
        if(myscore > 0){
            this._win!.active = true;
        }         
        else if(myscore < 0){
            this._lose!.active = true;
        }
        else{
            this._pingju!.active = true;
        }
        
            
        //显示玩家信息
        for(var i = 0; i < 4; ++i){
            var seatView = this._seats[i];
            var userData = data[i];
            var hued = false;
            //胡牌的玩家才显示 是否清一色 根xn的字样
            var numOfGangs = userData.angangs.length + userData.wangangs.length + userData.diangangs.length;
            // xzdd 的结算项一定会带 numofgen；这里断言非空只是类型需要，没有补判空。
            var numOfGen = userData.numofgen!;
            var actionArr = [];
            var is7pairs = false;
            var ischadajiao = false;
            for(var j = 0; j < userData.actions.length; ++j){
                var ac = userData.actions[j];
                if(ac.type == "zimo" || ac.type == "ganghua" || ac.type == "dianganghua" || ac.type == "hu" || ac.type == "gangpaohu" || ac.type == "qiangganghu" || ac.type == "chadajiao"){
                    if(userData.pattern == "7pairs"){
                        actionArr.push("七对");
                    }
                    else if(userData.pattern == "l7pairs"){
                        actionArr.push("龙七对");
                    }
                    else if(userData.pattern == "j7pairs"){
                        actionArr.push("将七对");
                    }
                    else if(userData.pattern == "duidui"){
                        actionArr.push("碰碰胡");
                    }
                    else if(userData.pattern == "jiangdui"){
                        actionArr.push("将对");
                    }
                    
                    if(ac.type == "zimo"){
                        actionArr.push("自摸");
                    }
                    else if(ac.type == "ganghua"){
                        actionArr.push("杠上花");
                    }
                    else if(ac.type == "dianganghua"){
                        actionArr.push("点杠花");
                    }
                    else if(ac.type == "gangpaohu"){
                        actionArr.push("杠炮胡");
                    }
                    else if(ac.type == "qiangganghu"){
                        actionArr.push("抢杠胡");
                    }
                    else if(ac.type == "chadajiao"){
                        ischadajiao = true;
                    }
                    hued = true;
                }
                else if(ac.type == "fangpao"){
                    actionArr.push("放炮");
                }
                else if(ac.type == "angang"){
                    actionArr.push("暗杠");
                }
                else if(ac.type == "diangang"){
                    actionArr.push("明杠");
                }
                else if(ac.type == "wangang"){
                    actionArr.push("弯杠");
                }
                else if(ac.type == "fanggang"){
                   actionArr.push("放杠");
                }
                else if(ac.type == "zhuanshougang"){
                    actionArr.push("转手杠");
                }
                else if(ac.type == "beiqianggang"){
                    actionArr.push("被抢杠");
                }
                else if(ac.type == "beichadajiao"){
                    actionArr.push("被查叫");
                }
            }
            
            if(hued){
                if(userData.qingyise){
                    actionArr.push("清一色");
                }
                
                if(userData.menqing){
                    actionArr.push("门清");
                }
                
                if(userData.zhongzhang){
                    actionArr.push("中张");
                }
                
                if(userData.jingouhu){
                    actionArr.push("金钩胡");
                }
                                
                if(userData.haidihu){
                    actionArr.push("海底胡");
                }
                
                if(userData.tianhu){
                    actionArr.push("天胡");
                }
                
                if(userData.dihu){
                    actionArr.push("地胡");
                }
            
                if(numOfGen > 0){
                    actionArr.push("根x" + numOfGen); 
                }                
                
                if(ischadajiao){
                    actionArr.push("查大叫");
                }
            }
            
            for(var o = 0; o < 3;++o){
                seatView.hu.children[o].active = false;    
            }
            if(userData.huorder! >= 0){
                seatView.hu.children[userData.huorder!].active = true;    
            }

            seatView.username.string = cc.vv.gameNetMgr.seats![i].name;
            seatView.zhuang.active = cc.vv.gameNetMgr.button == i;
            seatView.reason.string = actionArr.join("、");
            
            //胡牌的玩家才有番
            var fan = 0;
            if(hued){
                fan = userData.fan!;
            }
            seatView.fan!.string = fan + "番";
            
            //
            if(userData.score > 0){
                seatView.score.string = "+" + userData.score;    
            }
            else{
                // 老代码把数字直接赋给 Label.string（JS 里能跑），这里按运行期实际行为断言，不加转换。
                seatView.score.string = userData.score as unknown as string;
            }
           
            
            var hupai = -1;
            if(hued){
                hupai = userData.holds.pop()!;
            }
            
            cc.vv.mahjongmgr.sortMJ(userData.holds,userData.dingque!);
            
            //胡牌不参与排序
            if(hued){
                userData.holds.push(hupai);
            }
            
            //隐藏所有牌
            for(var k = 0; k < seatView.mahjongs.childrenCount; ++k){
                var n = seatView.mahjongs.children[k];
                n.active = false;
            }
           
            var lackingNum = (userData.pengs.length + numOfGangs)*3; 
            //显示相关的牌
            for(var k = 0; k < userData.holds.length; ++k){
                var pai = userData.holds[k];
                var n = seatView.mahjongs.children[k + lackingNum];
                n.active = true;
                var sprite = n.getComponent(cc.Sprite);
                sprite.spriteFrame = cc.vv.mahjongmgr.getSpriteFrameByMJID("M_",pai);
            }
            
            
            for(var k = 0; k < seatView._pengandgang.length; ++k){
                seatView._pengandgang[k].active = false;
            }
            
            //初始化杠牌
            var index = 0;
            var gangs = userData.angangs;
            for(var k = 0; k < gangs.length; ++k){
                var mjid = gangs[k];
                this.initPengAndGangs(seatView,index,mjid,"angang");
                index++;    
            }
            
            var gangs = userData.diangangs;
            for(var k = 0; k < gangs.length; ++k){
                var mjid = gangs[k];
                this.initPengAndGangs(seatView,index,mjid,"diangang");
                index++;    
            }
            
            var gangs = userData.wangangs;
            for(var k = 0; k < gangs.length; ++k){
                var mjid = gangs[k];
                this.initPengAndGangs(seatView,index,mjid,"wangang");
                index++;    
            }
            
            //初始化碰牌
            var pengs = userData.pengs
            if(pengs){
                for(var k = 0; k < pengs.length; ++k){
                    var mjid = pengs[k];
                    this.initPengAndGangs(seatView,index,mjid,"peng");
                    index++;    
                }    
            }
        }
    }

    onGameOver_XLCH(data: GameOverResultSeat[]){
        console.log(data);
        if(data.length == 0){
            this._gameresult!.active = true;
            return;
        }
        this._gameover!.active = true;
        this._pingju!.active = false;
        this._win!.active = false;
        this._lose!.active = false;

        var myscore = data[cc.vv.gameNetMgr.seatIndex].score;
        if(myscore > 0){
            this._win!.active = true;
        }         
        else if(myscore < 0){
            this._lose!.active = true;
        }
        else{
            this._pingju!.active = true;
        }
            
        //显示玩家信息
        for(var i = 0; i < 4; ++i){
            var seatView = this._seats[i];
            var userData = data[i];
            var hued = false;
            var actionArr = [];
            var is7pairs = false;
            var ischadajiao = false;
            var hupaiRoot = seatView.hupai;
            
            for(var j = 0; j < hupaiRoot.children.length; ++j){
                hupaiRoot.children[j].active = false;
            }
            
            var hi = 0;
            // xlch 才带 huinfo；这里断言非空只是类型需要，没有补判空。
            for(var j = 0; j < userData.huinfo!.length; ++j){
                var info = userData.huinfo![j];
                hued = hued || info.ishupai!;
                if(info.ishupai){
                    if(hi < hupaiRoot.children.length){
                        var hupaiView = hupaiRoot.children[hi]; 
                        hupaiView.active = true;
                        hupaiView.getComponent(cc.Sprite).spriteFrame = cc.vv.mahjongmgr.getSpriteFrameByMJID("B_",info.pai!);
                        hi++;   
                    }
                }
                
                var str = ""
                var sep = "";
                
                var dataseat = userData;
                if(!info.ishupai){
                    if(info.action == "fangpao"){
                        str = "放炮";
                    }
                    else if(info.action == "gangpao"){
                        str = "杠上炮";
                    }
                    else if(info.action == "beiqianggang"){
                        str = "被抢杠";
                    }
                    else{
                        str = "被查大叫";
                    }
                    
                    dataseat = data[info.target!]; 
                    info = dataseat.huinfo![info.index!];
                }
                else{
                    if(info.action == "hu"){
                        str = "接炮胡"
                    }
                    else if(info.action == "zimo"){
                        str = "自摸";
                    }
                    else if(info.action == "ganghua"){
                        str = "杠上花";
                    }
                    else if(info.action == "dianganghua"){
                        str = "点杠花";
                    }
                    else if(info.action == "gangpaohu"){
                        str = "杠炮胡";
                    }
                    else if(info.action == "qiangganghu"){
                        str = "抢杠胡";
                    }
                    else if(info.action == "chadajiao"){
                        str = "查大叫";
                    }   
                }
                
                str += "(";
                
                if(info.pattern == "7pairs"){
                    str += "七对";
                    sep = "、"
                }
                else if(info.pattern == "l7pairs"){
                    str += "龙七对";
                    sep = "、"
                }
                else if(info.pattern == "j7pairs"){
                    str += "将七对";
                    sep = "、"
                }
                else if(info.pattern == "duidui"){
                    str += "碰碰胡";
                    sep = "、"
                }
                else if(info.pattern == "jiangdui"){
                    str += "将对";
                    sep = "、"
                }
                    
                if(info.haidihu){
                    str += sep + "海底胡";
                    sep = "、";
                }
                
                if(info.tianhu){
                    str += sep + "天胡";
                    sep = "、";
                }
                
                if(info.dihu){
                    str += sep + "地胡";
                    sep = "、";
                }
                
                if(dataseat.qingyise){
                    str += sep + "清一色";
                    sep = "、";
                }
                
                if(dataseat.menqing){
                    str += sep + "门清";
                    sep = "、";
                }
                
                if(dataseat.jingouhu){
                    str += sep + "金钩胡";
                    sep = "、";
                }
                         
                if(dataseat.zhongzhang){
                    str += sep + "中张";
                    sep = "、";
                }
            
                if(info.numofgen! > 0){
                    str += sep + "根x" + info.numofgen;
                    sep = "、"; 
                }
                
                if(sep == ""){
                    str += "平胡";
                }
                
                str += "、" + info.fan + "番";
                
                str += ")";
                actionArr.push(str);
            }
            
            seatView.hu.active = hued;
            
            if(userData.angangs.length){
                actionArr.push("暗杠x" + userData.angangs.length);
            }
            
            if(userData.diangangs.length){
                actionArr.push("明杠x" + userData.diangangs.length);
            }
            
            if(userData.wangangs.length){
                actionArr.push("巴杠x" + userData.wangangs.length);
            }

            seatView.username.string = cc.vv.gameNetMgr.seats![i].name;
            seatView.zhuang.active = cc.vv.gameNetMgr.button == i;
            seatView.reason.string = actionArr.join("、");
            
            //
            if(userData.score > 0){
                seatView.score.string = "+" + userData.score;    
            }
            else{
                // 老代码把数字直接赋给 Label.string（JS 里能跑），这里按运行期实际行为断言，不加转换。
                seatView.score.string = userData.score as unknown as string;
            }
           
            //隐藏所有牌
            for(var k = 0; k < seatView.mahjongs.childrenCount; ++k){
                var n = seatView.mahjongs.children[k];
                n.active = false;
            }
            
            cc.vv.mahjongmgr.sortMJ(userData.holds,userData.dingque!);
            
            var numOfGangs = userData.angangs.length + userData.wangangs.length + userData.diangangs.length;
           
            var lackingNum = (userData.pengs.length + numOfGangs)*3; 
            //显示相关的牌
            for(var k = 0; k < userData.holds.length; ++k){
                var pai = userData.holds[k];
                var n = seatView.mahjongs.children[k + lackingNum];
                n.active = true;
                var sprite = n.getComponent(cc.Sprite);
                sprite.spriteFrame = cc.vv.mahjongmgr.getSpriteFrameByMJID("M_",pai);
            }
            
            
            for(var k = 0; k < seatView._pengandgang.length; ++k){
                seatView._pengandgang[k].active = false;
            }
            
            //初始化杠牌
            var index = 0;
            var gangs = userData.angangs;
            for(var k = 0; k < gangs.length; ++k){
                var mjid = gangs[k];
                this.initPengAndGangs(seatView,index,mjid,"angang");
                index++;    
            }
            
            var gangs = userData.diangangs;
            for(var k = 0; k < gangs.length; ++k){
                var mjid = gangs[k];
                this.initPengAndGangs(seatView,index,mjid,"diangang");
                index++;    
            }
            
            var gangs = userData.wangangs;
            for(var k = 0; k < gangs.length; ++k){
                var mjid = gangs[k];
                this.initPengAndGangs(seatView,index,mjid,"wangang");
                index++;    
            }
            
            //初始化碰牌
            var pengs = userData.pengs
            if(pengs){
                for(var k = 0; k < pengs.length; ++k){
                    var mjid = pengs[k];
                    this.initPengAndGangs(seatView,index,mjid,"peng");
                    index++;    
                }    
            }
        }
    }

    initPengAndGangs(seatView: GameOverSeatView,index: number,mjid: Pai,flag: string){
        var pgroot = null as cc.Node | null;
        if(seatView._pengandgang.length <= index){
            // cc.instantiate 在引擎声明里返回 any，这里按运行期实际取到的 cc.Node 断言。
            pgroot = cc.instantiate(cc.vv.mahjongmgr.pengPrefabSelf) as cc.Node;
            seatView._pengandgang.push(pgroot);
            seatView.mahjongs.addChild(pgroot);    
        }
        else{
            pgroot = seatView._pengandgang[index];
            pgroot.active = true;
        }
      
        // 引擎声明里 getComponentsInChildren 只返回 cc.Component，这里按运行期实际取到的 cc.Sprite 断言。
        var sprites = pgroot.getComponentsInChildren(cc.Sprite) as cc.Sprite[];
        for(var s = 0; s < sprites.length; ++s){
            var sprite = sprites[s];
            if(sprite.node.name == "gang"){
                var isGang = flag != "peng";
                sprite.node.active = isGang;
                sprite.node.scaleX = 1.0;
                sprite.node.scaleY = 1.0;
                if(flag == "angang"){
                    sprite.spriteFrame = cc.vv.mahjongmgr.getEmptySpriteFrame("myself");
                    sprite.node.scaleX = 1.4;
                    sprite.node.scaleY = 1.4;                        
                }   
                else{
                    sprite.spriteFrame = cc.vv.mahjongmgr.getSpriteFrameByMJID("B_",mjid);    
                }
            }
            else{ 
                sprite.spriteFrame = cc.vv.mahjongmgr.getSpriteFrameByMJID("B_",mjid);
            }
        }
        pgroot.x = index * 55 * 3 + index * 10;
    }

    onBtnReadyClicked(){
        console.log("onBtnReadyClicked");
        if(this._isGameEnd){
            this._gameresult!.active = true;
        }
        else{
            cc.vv.net.send('ready');   
        }
        this._gameover!.active = false;
    }

    onBtnShareClicked(){
        console.log("onBtnShareClicked");
    }
    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = GameOver;
