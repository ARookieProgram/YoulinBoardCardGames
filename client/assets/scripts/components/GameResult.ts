/** 结算面板里的一行座位（`Seat` 组件）；这里只声明本文件真正调用的成员。
 *  按类名 `getComponent("Seat")` 在 creator.d.ts 里只返回 cc.Component，所以调用点需要断言。 */
interface ResultSeat {
    node: cc.Node;
    setInfo(name: string, score: number | null, dayingjia: boolean): void;
    setID(id: number): void;
}

const { ccclass, property } = cc._decorator;

@ccclass
export default class GameResult extends cc.Component {
    // foo: {
    //    default: null,
    //    url: cc.Texture2D,  // optional, default is typeof default
    //    serializable: true, // optional, default is true
    //    visible: true,      // optional, default is true
    //    displayName: 'Foo', // optional
    //    readonly: false,    // optional, default is false
    // },
    // ...
    @property _gameresult: cc.Node | null = null;
    @property _seats: ResultSeat[] = [];

    // use this for initialization
    onLoad() {
        if(cc.vv == null){
            return;
        }
        
        this._gameresult = this.node.getChildByName("game_result");
        //this._gameresult.active = false;
        
        var seats = this._gameresult!.getChildByName("seats");
        for(var i = 0; i < seats.children.length; ++i){
            // 按类名取组件在 creator.d.ts 里只返回 cc.Component，这里断言成 Seat 组件（只作用于类型）。
            this._seats.push(seats.children[i].getComponent("Seat") as unknown as ResultSeat);   
        }
        
        var btnClose = cc.find("Canvas/game_result/btnClose");
        if(btnClose){
            // 第 2 个参数运行期就是 this.node（Utils.js 直接把它赋给 eventHandler.target）。
            cc.vv.utils.addClickEvent(btnClose,this.node,"GameResult","onBtnCloseClicked");
        }
        
        var btnShare = cc.find("Canvas/game_result/btnShare");
        if(btnShare){
            cc.vv.utils.addClickEvent(btnShare,this.node,"GameResult","onBtnShareClicked");
        }
        
        //初始化网络事件监听器
        var self = this;
        this.node.on('game_end',function(data: EndInfo[]){self.onGameEnd(data);});
    }

    showResult(seat: ResultSeat,info: EndInfo,isZuiJiaPaoShou: boolean){
        seat.node.getChildByName("zuijiapaoshou").active = isZuiJiaPaoShou;
        
        // 老代码直接把 number 赋给 cc.Label.string（运行期由 Label 自己处理），
        // 这里只加类型断言，赋的值与运行期行为一字未改。
        seat.node.getChildByName("zimocishu").getComponent(cc.Label).string = info.numzimo as unknown as string;
        seat.node.getChildByName("jiepaocishu").getComponent(cc.Label).string = info.numjiepao as unknown as string;
        seat.node.getChildByName("dianpaocishu").getComponent(cc.Label).string = info.numdianpao as unknown as string;
        seat.node.getChildByName("angangcishu").getComponent(cc.Label).string = info.numangang as unknown as string;
        seat.node.getChildByName("minggangcishu").getComponent(cc.Label).string = info.numminggang as unknown as string;
        seat.node.getChildByName("chajiaocishu").getComponent(cc.Label).string = info.numchadajiao as unknown as string;
    }

    onGameEnd(endinfo: EndInfo[]){
        // `seats` 老代码没判空（能收到 game_end 时座位一定在），沿用非空断言。
        var seats = cc.vv.gameNetMgr.seats!;
        var maxscore = -1;
        var maxdianpao = 0;
        var dianpaogaoshou = -1;
        for(var i = 0; i < seats.length; ++i){
            var seat = seats[i];
            // seat.score 声明成可空，老代码直接比较大小时没有判空，沿用非空断言。
            if(seat.score! > maxscore){
                maxscore = seat.score!;
            }
            if(endinfo[i].numdianpao > maxdianpao){
                maxdianpao = endinfo[i].numdianpao;
                dianpaogaoshou = i;
            }
        }
        
        for(var i = 0; i < seats.length; ++i){
            var seat = seats[i];
            var isBigwin = false;
            if(seat.score! > 0){
                isBigwin = seat.score == maxscore;
            }
            this._seats[i].setInfo(seat.name,seat.score, isBigwin);
            this._seats[i].setID(seat.userid);
            var isZuiJiaPaoShou = dianpaogaoshou == i;
            this.showResult(this._seats[i],endinfo[i],isZuiJiaPaoShou);
        }
    }

    onBtnCloseClicked(){
        cc.vv.wc.show('正在返回游戏大厅');
        cc.director.loadScene("hall");
    }

    onBtnShareClicked(){
        cc.vv.anysdkMgr.shareResult();
    }
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = GameResult;
