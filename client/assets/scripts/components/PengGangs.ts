// 碰杠：四个座位碰牌/杠牌的摆放与显示。
//
// 本文件是 ES5 风格（cc.Class / var / function）的 TypeScript 迁移产物：
// 运行时行为与迁移前的 PengGangs.js 完全一致，只补了类型标注与本地事件载荷的类型断言。
cc.Class({
    extends: cc.Component,

    properties: {
        // foo: {
        //    default: null,
        //    url: cc.Texture2D,  // optional, default is typeof default
        //    serializable: true, // optional, default is true
        //    visible: true,      // optional, default is true
        //    displayName: 'Foo', // optional
        //    readonly: false,    // optional, default is false
        // },
        // ...
    },

    // use this for initialization
    onLoad: function () {
        if(!cc.vv){
            return;
        }
        
        var gameChild = this.node.getChildByName("game");
        var myself = gameChild.getChildByName("myself");
        var pengangroot = myself.getChildByName("penggangs");
        var cvs = cc.find('Canvas');
        var realwidth = cvs.width;
        var scale = realwidth / 1280;
        pengangroot.scaleX *= scale;
        pengangroot.scaleY *= scale;
        
        var self = this;
        this.node.on('peng_notify',function(data){
            //刷新所有的牌
            // peng_notify 派发的就是座位对象（GameNetMgr.doPeng 里传的 seatData）。
            self.onPengGangChanged(data as SeatData);
        });
        
        this.node.on('gang_notify',function(data){
            //刷新所有的牌
            // gang_notify 派发的是 { seatData, gangtype }（GameNetMgr.doGang 里组装的本地载荷）。
            self.onPengGangChanged((data as GangNotifyLocal).seatData);
        });
        
        this.node.on('game_begin',function(data){
            self.onGameBein();
        });
        
        // 老代码不判空：seats 为 null 时运行期行为与迁移前一致。
        var seats = cc.vv.gameNetMgr.seats!;
        for(var i in seats){
            // for...in 的循环变量类型是 string，老代码就是按下标取的，这里只补一次类型断言。
            this.onPengGangChanged(seats[i as unknown as number]);
        }
    },
    
    onGameBein:function(){
        this.hideSide("myself");
        this.hideSide("right");
        this.hideSide("up");
        this.hideSide("left");
    },
    
    hideSide:function(side: string){
        var gameChild = this.node.getChildByName("game");
        var myself = gameChild.getChildByName(side);
        var pengangroot = myself.getChildByName("penggangs");
        if(pengangroot){
            for(var i = 0; i < pengangroot.childrenCount; ++i){
                pengangroot.children[i].active = false;
            }            
        }
    },
    
    onPengGangChanged:function(seatData: SeatData){
        
        if(seatData.angangs == null && seatData.diangangs == null && seatData.wangangs == null && seatData.pengs == null){
            return;
        }
        var localIndex = cc.vv.gameNetMgr.getLocalIndex(seatData.seatindex);
        var side = cc.vv.mahjongmgr.getSide(localIndex);
        var pre = cc.vv.mahjongmgr.getFoldPre(localIndex);
       
        console.log("onPengGangChanged" + localIndex);
            
        var gameChild = this.node.getChildByName("game");
        var myself = gameChild.getChildByName(side);
        var pengangroot = myself.getChildByName("penggangs");
        
        for(var i = 0; i < pengangroot.childrenCount; ++i){
            pengangroot.children[i].active = false;
        }
        //初始化杠牌
        var index = 0;
        
        var gangs = seatData.angangs
        for(var i = 0; i < gangs.length; ++i){
            var mjid = gangs[i];
            this.initPengAndGangs(pengangroot,side,pre,index,mjid,"angang");
            index++;    
        } 
        var gangs = seatData.diangangs
        for(var i = 0; i < gangs.length; ++i){
            var mjid = gangs[i];
            this.initPengAndGangs(pengangroot,side,pre,index,mjid,"diangang");
            index++;    
        }
        
        var gangs = seatData.wangangs
        for(var i = 0; i < gangs.length; ++i){
            var mjid = gangs[i];
            this.initPengAndGangs(pengangroot,side,pre,index,mjid,"wangang");
            index++;    
        }
        
        //初始化碰牌
        var pengs = seatData.pengs
        if(pengs){
            for(var i = 0; i < pengs.length; ++i){
                var mjid = pengs[i];
                this.initPengAndGangs(pengangroot,side,pre,index,mjid,"peng");
                index++;    
            }    
        }        
    },
    
    initPengAndGangs:function(pengangroot: cc.Node,side: string,pre: string,index: number,mjid: Pai,flag: string){
        var pgroot: cc.Node | null = null;
        if(pengangroot.childrenCount <= index){
            if(side == "left" || side == "right"){
                // cc.instantiate 的声明返回 any，这里按运行期实际类型（节点）断言。
                pgroot = cc.instantiate(cc.vv.mahjongmgr.pengPrefabLeft) as cc.Node;
            }
            else{
                pgroot = cc.instantiate(cc.vv.mahjongmgr.pengPrefabSelf) as cc.Node;
            }
            
            pengangroot.addChild(pgroot);    
        }
        else{
            pgroot = pengangroot.children[index];
            pgroot.active = true;
        }
        
        if(side == "left"){
            pgroot.y = -(index * 25 * 3);                    
        }
        else if(side == "right"){
            pgroot.y = (index * 25 * 3);
            pgroot.setLocalZOrder(-index);
        }
        else if(side == "myself"){
            pgroot.x = index * 55 * 3 + index * 10;                    
        }
        else{
            pgroot.x = -(index * 55*3);
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
                    sprite.spriteFrame = cc.vv.mahjongmgr.getEmptySpriteFrame(side);
                    if(side == "myself" || side == "up"){
                        sprite.node.scaleX = 1.4;
                        sprite.node.scaleY = 1.4;                        
                    }
                }   
                else{
                    sprite.spriteFrame = cc.vv.mahjongmgr.getSpriteFrameByMJID(pre,mjid);    
                }
            }
            else{ 
                sprite.spriteFrame = cc.vv.mahjongmgr.getSpriteFrameByMJID(pre,mjid);
            }
        }
    },

    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
});

/** `gang_notify` 本地事件的载荷形状（`GameNetMgr.doGang` 组装，不是网络原始载荷）。 */
interface GangNotifyLocal {
    seatData: SeatData;
    gangtype: string;
}

export { };
