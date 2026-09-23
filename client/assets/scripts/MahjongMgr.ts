var mahjongSprites: string[] = [];

cc.Class({
    extends: cc.Component,

    // properties 里都是编辑器拖上去的资源：运行时由场景注入，构造期初值仍是 null。
    // 这里用 `null as unknown as X` 把类型断言成非空（`null as X` 会被 TS 判为不相关而报错），
    // 只为让 `this` 满足 `MahjongMgr` 接口；是纯类型标注，不产生任何运行时代码。
    properties: {
        leftAtlas:{
            default:null as unknown as cc.SpriteAtlas,
            type:cc.SpriteAtlas
        },
        
        rightAtlas:{
            default:null as unknown as cc.SpriteAtlas,
            type:cc.SpriteAtlas
        },
        
        bottomAtlas:{
            default:null as unknown as cc.SpriteAtlas,
            type:cc.SpriteAtlas
        },
        
        bottomFoldAtlas:{
            default:null as unknown as cc.SpriteAtlas,
            type:cc.SpriteAtlas
        },
        
        pengPrefabSelf:{
            default:null as unknown as cc.Prefab,
            type:cc.Prefab
        },
        
        pengPrefabLeft:{
            default:null as unknown as cc.Prefab,
            type:cc.Prefab
        },
        
        emptyAtlas:{
            default:null as unknown as cc.SpriteAtlas,
            type:cc.SpriteAtlas
        },
        
        holdsEmpty:{
            default:[] as cc.SpriteFrame[],
            type:[cc.SpriteFrame]
        },
        
        _sides:null as string[] | null,
        _pres:null as string[] | null,
        _foldPres:null as string[] | null,
    },
    
    onLoad:function(){
        if(cc.vv == null){
            return;
        }
        this._sides = ["myself","right","up","left"];
        this._pres = ["M_","R_","B_","L_"];
        this._foldPres = ["B_","R_","B_","L_"];
        cc.vv.mahjongmgr = this; 
        //筒
        for(var i = 1; i < 10; ++i){
            mahjongSprites.push("dot_" + i);        
        }
        
        //条
        for(var i = 1; i < 10; ++i){
            mahjongSprites.push("bamboo_" + i);
        }
        
        //万
        for(var i = 1; i < 10; ++i){
            mahjongSprites.push("character_" + i);
        }
        
        //中、发、白
        mahjongSprites.push("red");
        mahjongSprites.push("green");
        mahjongSprites.push("white");
        
        //东西南北风
        mahjongSprites.push("wind_east");
        mahjongSprites.push("wind_west");
        mahjongSprites.push("wind_south");
        mahjongSprites.push("wind_north");
    },
    
    getMahjongSpriteByID:function(id: Pai){
        return mahjongSprites[id];
    },
    
    getMahjongType:function(id: Pai){
      if(id >= 0 && id < 9){
          return 0;
      }
      else if(id >= 9 && id < 18){
          return 1;
      }
      else if(id >= 18 && id < 27){
          return 2;
      }
    },
    
    // 老代码在 pre 不是 M_/B_/L_/R_ 时会隐式返回 undefined，这里用 `this: MahjongMgr` +
    // 函数类型断言把返回类型收成接口声明的 cc.SpriteFrame；断言可擦除，运行时代码逐字不变。
    getSpriteFrameByMJID: (function (this: MahjongMgr,pre: string,mjid: Pai){
        var spriteFrameName = this.getMahjongSpriteByID(mjid);
        spriteFrameName = pre + spriteFrameName;
        if(pre == "M_"){
            return this.bottomAtlas.getSpriteFrame(spriteFrameName);            
        }
        else if(pre == "B_"){
            return this.bottomFoldAtlas.getSpriteFrame(spriteFrameName);
        }
        else if(pre == "L_"){
            return this.leftAtlas.getSpriteFrame(spriteFrameName);
        }
        else if(pre == "R_"){
            return this.rightAtlas.getSpriteFrame(spriteFrameName);
        }
    }) as (pre: string,mjid: Pai) => cc.SpriteFrame,
    
    getAudioURLByMJID:function(id: Pai){
        var realId = 0;
        if(id >= 0 && id < 9){
            realId = id + 21;
        }
        else if(id >= 9 && id < 18){
            realId = id - 8;
        }
        else if(id >= 18 && id < 27){
            realId = id - 7;
        }
        return "nv/" + realId + ".mp3";
    },
    
    getEmptySpriteFrame: (function (this: MahjongMgr,side: string){
        if(side == "up"){
            return this.emptyAtlas.getSpriteFrame("e_mj_b_up");
        }   
        else if(side == "myself"){
            return this.emptyAtlas.getSpriteFrame("e_mj_b_bottom");
        }
        else if(side == "left"){
            return this.emptyAtlas.getSpriteFrame("e_mj_b_left");
        }
        else if(side == "right"){
            return this.emptyAtlas.getSpriteFrame("e_mj_b_right");
        }
    }) as (side: string) => cc.SpriteFrame,
    
    getHoldsEmptySpriteFrame: (function (this: MahjongMgr,side: string){
        if(side == "up"){
            return this.emptyAtlas.getSpriteFrame("e_mj_up");
        }   
        else if(side == "myself"){
            return null;
        }
        else if(side == "left"){
            return this.emptyAtlas.getSpriteFrame("e_mj_left");
        }
        else if(side == "right"){
            return this.emptyAtlas.getSpriteFrame("e_mj_right");
        }
    }) as (side: string) => cc.SpriteFrame | null,
    
    sortMJ:function(mahjongs: PaiList,dingque: number){
        var self = this;
        mahjongs.sort(function(a,b){
            if(dingque >= 0){
                var t1 = self.getMahjongType(a);
                var t2 = self.getMahjongType(b);
                if(t1 != t2){
                    if(dingque == t1){
                        return 1;
                    }
                    else if(dingque == t2){
                        return -1;
                    }
                }
            }
            return a - b;
        });
    },
    
    getSide:function(localIndex: number){
        return this._sides![localIndex];
    },
    
    getPre:function(localIndex: number){
        return this._pres![localIndex];
    },
    
    getFoldPre:function(localIndex: number){
        return this._foldPres![localIndex];
    }
});

export { };
