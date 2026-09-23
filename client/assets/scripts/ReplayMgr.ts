var ACTION_CHUPAI = 1;
var ACTION_MOPAI = 2;
var ACTION_PENG = 3;
var ACTION_GANG = 4;
var ACTION_HU = 5;

const { ccclass, property } = cc._decorator;

@ccclass
export default class ReplayMgr extends cc.Component {
    // foo: {
    //    default: null,
    //    url: cc.Texture2D,  // optional, default is typeof default
    //    serializable: true, // optional, default is true
    //    visible: true,      // optional, default is true
    //    displayName: 'Foo', // optional
    //    readonly: false,    // optional, default is false
    // },
    // ...
    @property _lastAction: ReplayAction | null = null;
    @property _actionRecords: number[] | null = null;
    @property _currentIndex: number = 0;
    // 老代码在动作类型不在 1~5 之内时会隐式返回 undefined，接口声明的是延时的秒数（number）；
    // 这里用 `this: ReplayMgr` + 函数类型断言收口返回类型，断言可擦除，运行时代码逐字不变。
    // 类方法挂不了 `as`，所以它写成挂在实例上的函数字段：调用方式与运行期行为不变。
    takeAction = (function (this: ReplayMgr){
        var action = this.getNextAction();
        if(this._lastAction != null && this._lastAction.type == ACTION_CHUPAI){
            if(action != null && action.type != ACTION_PENG && action.type != ACTION_GANG && action.type != ACTION_HU){
                cc.vv.gameNetMgr.doGuo(this._lastAction.si,this._lastAction.pai);
            }
        }
        this._lastAction = action;
        if(action == null){
            return -1;
        }
        var nextActionDelay = 1.0;
        if(action.type == ACTION_CHUPAI){
            //console.log("chupai");
            cc.vv.gameNetMgr.doChupai(action.si,action.pai);
            return 1.0;
        }
        else if(action.type == ACTION_MOPAI){
            //console.log("mopai");
            cc.vv.gameNetMgr.doMopai(action.si,action.pai);
            cc.vv.gameNetMgr.doTurnChange(action.si);
            return 0.5;
        }
        else if(action.type == ACTION_PENG){
            //console.log("peng");
            cc.vv.gameNetMgr.doPeng(action.si,action.pai);
            cc.vv.gameNetMgr.doTurnChange(action.si);
            return 1.0;
        }
        else if(action.type == ACTION_GANG){
            //console.log("gang");
            cc.vv.gameNetMgr.dispatchEvent('hangang_notify',action.si);
            cc.vv.gameNetMgr.doGang(action.si,action.pai);
            cc.vv.gameNetMgr.doTurnChange(action.si);
            return 1.0;
        }
        else if(action.type == ACTION_HU){
            //console.log("hu");
            cc.vv.gameNetMgr.doHu({seatindex:action.si,hupai:action.pai,iszimo:false});
            return 1.5;
        }
    }) as () => number;

    // use this for initialization
    onLoad() {

    }

    clear(){
        this._lastAction = null;
        this._actionRecords = null;
        this._currentIndex = 0;
    }

    init(data: ReplayDetail){
        this._actionRecords = data.action_records;
        if(this._actionRecords == null){
            // 老代码的兜底分支赋的是空对象而不是空数组，这里原样保留，只用一次断言过类型
            this._actionRecords = {} as number[];
        }
        this._currentIndex = 0;
        this._lastAction = null;
    }

    isReplay(){
        return this._actionRecords != null;    
    }

    getNextAction(){
        if(this._currentIndex >= this._actionRecords!.length){
            return null;
        }
        
        var si = this._actionRecords![this._currentIndex++];
        var action = this._actionRecords![this._currentIndex++];
        var pai = this._actionRecords![this._currentIndex++];
        return {si:si,type:action,pai:pai};
    }
    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = ReplayMgr;
