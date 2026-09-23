var mahjongSprites: string[] = [];

const { ccclass, property } = cc._decorator;

@ccclass
export default class MahjongMgr extends cc.Component {
    @property({type: cc.SpriteAtlas}) leftAtlas: cc.SpriteAtlas = null as unknown as cc.SpriteAtlas;

    @property({type: cc.SpriteAtlas}) rightAtlas: cc.SpriteAtlas = null as unknown as cc.SpriteAtlas;

    @property({type: cc.SpriteAtlas}) bottomAtlas: cc.SpriteAtlas = null as unknown as cc.SpriteAtlas;

    @property({type: cc.SpriteAtlas}) bottomFoldAtlas: cc.SpriteAtlas = null as unknown as cc.SpriteAtlas;

    @property({type: cc.Prefab}) pengPrefabSelf: cc.Prefab = null as unknown as cc.Prefab;

    @property({type: cc.Prefab}) pengPrefabLeft: cc.Prefab = null as unknown as cc.Prefab;

    @property({type: cc.SpriteAtlas}) emptyAtlas: cc.SpriteAtlas = null as unknown as cc.SpriteAtlas;

    @property({type: [cc.SpriteFrame]}) holdsEmpty: cc.SpriteFrame[] = [] as cc.SpriteFrame[];

    @property _sides: string[] | null = null;
    @property _pres: string[] | null = null;
    @property _foldPres: string[] | null = null;
    // 老代码在 pre 不是 M_/B_/L_/R_ 时会隐式返回 undefined，这里用 `this: MahjongMgr` +
    // 函数类型断言把返回类型收成接口声明的 cc.SpriteFrame；断言可擦除，运行时代码逐字不变。
    // 类方法挂不了 `as`，所以这三个方法写成挂在实例上的函数字段：调用方式与运行期行为不变。
    getSpriteFrameByMJID = (function (this: MahjongMgr,pre: string,mjid: Pai){
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
    }) as (pre: string,mjid: Pai) => cc.SpriteFrame;

    getEmptySpriteFrame = (function (this: MahjongMgr,side: string){
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
    }) as (side: string) => cc.SpriteFrame;

    getHoldsEmptySpriteFrame = (function (this: MahjongMgr,side: string){
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
    }) as (side: string) => cc.SpriteFrame | null;

    onLoad(){
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
    }

    getMahjongSpriteByID(id: Pai){
        return mahjongSprites[id];
    }

    getMahjongType(id: Pai){
      if(id >= 0 && id < 9){
          return 0;
      }
      else if(id >= 9 && id < 18){
          return 1;
      }
      else if(id >= 18 && id < 27){
          return 2;
      }
    }

    getAudioURLByMJID(id: Pai){
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
    }

    sortMJ(mahjongs: PaiList,dingque: number){
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
    }

    getSide(localIndex: number){
        return this._sides![localIndex];
    }

    getPre(localIndex: number){
        return this._pres![localIndex];
    }

    getFoldPre(localIndex: number){
        return this._foldPres![localIndex];
    }
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = MahjongMgr;
