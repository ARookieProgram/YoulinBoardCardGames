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
        _folds:null as { [side: string]: cc.Sprite[] } | null,
    },

    // use this for initialization
    onLoad: function () {
        if(cc.vv == null){
            return;
        }
        
        this.initView();
        this.initEventHandler();
        
        this.initAllFolds();
    },
    
    initView:function(){
        this._folds = {};
        var game = this.node.getChildByName("game");
        var sides = ["myself","right","up","left"];
        for(var i = 0; i < sides.length; ++i){
            var sideName = sides[i];
            var sideRoot = game.getChildByName(sideName);
            var folds = [];
            var foldRoot = sideRoot.getChildByName("folds");
            for(var j = 0; j < foldRoot.children.length; ++j){
                var n = foldRoot.children[j];
                n.active = false;
                var sprite = n.getComponent(cc.Sprite); 
                // 引擎把 spriteFrame 声明成非空，老代码这里就是清空它；断言只影响类型，值仍是 null。
                sprite.spriteFrame = null as unknown as cc.SpriteFrame;
                folds.push(sprite);            
            }
            this._folds[sideName] = folds; 
        }
        
        this.hideAllFolds();
    },
    
    hideAllFolds:function(){
        for(var k in this._folds){
            // 老代码这里写的是内层循环的 i（var 提升，此刻是 undefined），照旧不改：
            // 运行时仍是 this._folds[undefined]，这个函数实际不做事。`i!` 只是让 tsc 接受这种写法。
            var f: cc.Sprite[] = this._folds![i!];
            for(var i in f){
                f[i].node.active = false;
            }
        }
    },
    
    initEventHandler:function(){
        var self = this;
        this.node.on('game_begin',function(data){
            self.initAllFolds();
        });  
        
        this.node.on('game_sync',function(data){
            self.initAllFolds();
        });
        
        this.node.on('game_chupai_notify',function(data){
            // 老代码直接把载荷当座位传进去（实际派发的是 {seatData,pai}，读 .folds 得 undefined 后提前返回），照旧。
            self.initFolds(data as SeatData);
        });
        
        this.node.on('guo_notify',function(data){
            self.initFolds(data as SeatData);
        });
    },
    
    initAllFolds:function(){
        var seats = cc.vv.gameNetMgr.seats;
        for(var i in seats){
            // for...in 的键是字符串，老代码直接拿它当数组下标（运行时等价），这里断言成 number 供类型检查。
            this.initFolds(seats![i as unknown as number]);
        }
    },
    
    initFolds:function(seatData: SeatData){
        var folds = seatData.folds;
        if(folds == null){
            return;
        }
        var localIndex = cc.vv.gameNetMgr.getLocalIndex(seatData.seatindex);
        var pre = cc.vv.mahjongmgr.getFoldPre(localIndex);
        var side = cc.vv.mahjongmgr.getSide(localIndex);
        
        var foldsSprites = this._folds![side];
        for(var i = 0; i < foldsSprites.length; ++i){
            var index = i;
            if(side == "right" || side == "up"){
                index = foldsSprites.length - i - 1;
            }
            var sprite = foldsSprites[index];
            sprite.node.active = true;
            this.setSpriteFrameByMJID(pre,sprite,folds[i]);
        }
        for(var i = folds.length; i < foldsSprites.length; ++i){
            var index = i;
            if(side == "right" || side == "up"){
                index = foldsSprites.length - i - 1;
            }
            var sprite = foldsSprites[index];
            
            sprite.spriteFrame = null as unknown as cc.SpriteFrame;
            sprite.node.active = false;
        }  
    },
    
    setSpriteFrameByMJID:function(pre: string, sprite: cc.Sprite, mjid: Pai){
        sprite.spriteFrame = cc.vv.mahjongmgr.getSpriteFrameByMJID(pre,mjid);
        sprite.node.active = true;
    },

    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
});

export { };
