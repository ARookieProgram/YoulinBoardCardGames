// 换三张：选牌、换牌提示与换牌结果的显示。
//
// 本文件用 ES6 class + @ccclass/@property 装饰器（Creator 2.4 的官方写法）：
// 运行时行为与迁移前的 HuanSanZhang.js 完全一致，只补了类型标注、可空属性的 `!` 断言
// 与本地事件载荷的类型断言。

const { ccclass, property } = cc._decorator;

@ccclass
export default class HuanSanZhang extends cc.Component {
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
    @property _huanpaitip: cc.Node | null = null;
    // 选中的牌节点，运行期就地增删；初值仍是空数组。
    @property _huanpaiArr: cc.Node[] = [];

    // use this for initialization
    onLoad() {
        this._huanpaitip = cc.find("Canvas/huansanzhang");
        this._huanpaitip!.active = cc.vv.gameNetMgr.isHuanSanZhang;
        
        if(this._huanpaitip!.active){
            this.showHuanpai(cc.vv.gameNetMgr.getSelfData().huanpais == null);
        }
        this.initHuaipaiInfo();
        
        var btnOk = cc.find("Canvas/huansanzhang/btn_ok");
        if(btnOk){
            // 老代码传的就是 this.node（Utils.js 直接把它赋给 eventHandler.target）。
            cc.vv.utils.addClickEvent(btnOk,this.node,"HuanSanZhang","onHuanSanZhang");
        }
        
        var self = this;
        this.node.on('game_begin',function(data){
            self.initHuaipaiInfo();
        });
        
        this.node.on('game_huanpai',function(data){
           self._huanpaitip!.active = true;
           self.showHuanpai(true);
        });
        
        this.node.on('huanpai_notify',function(data){
            // 本地事件派发的是 GameNetMgr 找到的座位对象（SeatData），不是网络原始载荷。
            if((data as SeatData).seatindex == cc.vv.gameNetMgr.seatIndex){
                self.initHuaipaiInfo();   
            }
        });
        
        this.node.on('game_huanpai_over',function(data){
            self._huanpaitip!.active = false;
            for(var i = 0; i < self._huanpaiArr.length; ++i){
                self._huanpaiArr[i].y = 0;
            }
            self._huanpaiArr = [];
            self.initHuaipaiInfo();
        });
        
        this.node.on('game_huanpai_result',function(data){
            cc.vv.gameNetMgr.isHuanSanZhang = false;
            self._huanpaitip!.active = false;
            for(var i = 0; i < self._huanpaiArr.length; ++i){
                self._huanpaiArr[i].y = 0;
            }
            self._huanpaiArr = [];
        });
        
        this.node.on('mj_clicked',function(data){
            // mj_clicked 派发的就是被点击的牌节点本身（Seat.js 里 emit 的就是节点）。
            var target = data as cc.Node;
            //如果已经点起来，则取消
            var idx = self._huanpaiArr.indexOf(target); 
            if(idx != -1){
                target.y = 0;
                self._huanpaiArr.splice(idx,1);
            }
            else{
                //如果是新的，则加入
                if(self._huanpaiArr.length < 3){
                    self._huanpaiArr.push(target);
                    target.y = 15;
                }
            } 
        });
    }

    showHuanpai(interactable: boolean){
        this._huanpaitip!.getChildByName("info").getComponent(cc.Label).string = interactable? "请选择三张一样花色的牌":"等待其他玩家选牌...";
        this._huanpaitip!.getChildByName("btn_ok").getComponent(cc.Button).interactable = interactable;
        this._huanpaitip!.getChildByName("mask").active = false;        
    }

    initHuaipaiInfo(){
        var huaipaiinfo = cc.find("Canvas/game/huanpaiinfo");
        var seat = cc.vv.gameNetMgr.getSelfData();
        if(seat.huanpais == null){
            huaipaiinfo.active = false;
            return;
        }
        huaipaiinfo.active = true;
        for(var i = 0; i < seat.huanpais.length; ++i){
            huaipaiinfo.getChildByName("hp" + (i + 1)).getComponent(cc.Sprite).spriteFrame = cc.vv.mahjongmgr.getSpriteFrameByMJID("M_",seat.huanpais[i]);
        }
        
        var hpm = huaipaiinfo.getChildByName("hpm");
        hpm.active = true;
        if(cc.vv.gameNetMgr.huanpaimethod == 0){
            hpm.rotation = 90;
        }
        else if(cc.vv.gameNetMgr.huanpaimethod == 1){
            hpm.rotation = 0;
        }
        else if(cc.vv.gameNetMgr.huanpaimethod == 2){
            hpm.rotation = 180;
        }
        else{
            hpm.active = false;
        }
    }

    onHuanSanZhang(event: cc.Event){
        if(this._huanpaiArr.length != 3){
            return;
        }
        
        var type: number | null | undefined = null;
        for(var i = 0; i < this._huanpaiArr.length; ++i){
            // 牌节点上的 mjId 声明为 number | null，老代码不判空。
            var pai = this._huanpaiArr[i].mjId!;
            var nt = cc.vv.mahjongmgr.getMahjongType(pai); 
            if(type == null){
                type = nt;
            }
            else{
                if(type != nt){
                    return;
                }
            }
        }
        
        var data = {
            p1:this._huanpaiArr[0].mjId,
            p2:this._huanpaiArr[1].mjId,
            p3:this._huanpaiArr[2].mjId,
        }
        
        this._huanpaitip!.getChildByName("info").getComponent(cc.Label).string = "等待其他玩家选牌...";
        this._huanpaitip!.getChildByName("btn_ok").getComponent(cc.Button).interactable = false;
        this._huanpaitip!.getChildByName("mask").active = true;
        
        cc.vv.net.send("huanpai",data);
    }
    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = HuanSanZhang;
