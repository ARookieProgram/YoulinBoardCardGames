// 定缺：定缺选择界面、推荐花色动画与各座位的定缺标记。
//
// 本文件是 ES5 风格（cc.Class / var / function）的 TypeScript 迁移产物：
// 运行时行为与迁移前的 DingQue.js 完全一致，只补了类型标注、可空属性的 `!` 断言
// 与本地事件载荷的类型断言。
cc.Class({
    extends: cc.Component,

    properties: {
        queYiMen:null as cc.Node | null,
        // 三个提示文本与三块选中遮罩、四个座位的定缺标记，运行期在 initView 里 push 进来。
        tips:[] as cc.Label[],
        selected:[] as cc.Node[],
        dingques:[] as cc.Node[],
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
    start: function () {
        if(cc.vv == null){
            return;
        }
        this.initView();
        this.initDingQue();
        this.initEventHandlers();
    },
    
    initView:function(){
        var gameChild = this.node.getChildByName("game");
        this.queYiMen = gameChild.getChildByName("dingque");
        this.queYiMen!.active = cc.vv.gameNetMgr.isDingQueing;
        
        var arr = ["myself","right","up","left"];
        for(var i = 0; i < arr.length; ++i){
            var side = gameChild.getChildByName(arr[i]);
            var seat = side.getChildByName("seat");
            var dingque = seat.getChildByName("que");
            this.dingques.push(dingque);
        }
        this.reset();
        
        var tips = this.queYiMen!.getChildByName("tips");
        for(var i = 0; i < tips.childrenCount; ++i){
            var n = tips.children[i];
            this.tips.push(n.getComponent(cc.Label));
        }
        
        if(cc.vv.gameNetMgr.gamestate == "dingque"){
            this.showDingQueChoice();
        }
    },
    
    initEventHandlers:function(){
        var self = this;
        this.node.on('game_dingque',function(data){
            self.showDingQueChoice();
        });
        
        this.node.on('game_dingque_notify',function(data){
            // 这个事件的载荷是用户 id（GameNetMgr 直接透传服务端下发的数字）。
            var seatIndex = cc.vv.gameNetMgr.getSeatIndexByID(data as number);
            var localIndex = cc.vv.gameNetMgr.getLocalIndex(seatIndex);
            console.log("game_dingque_notify:" + localIndex);
            self.tips[localIndex].node.active = true;
        });
        
        this.node.on('game_dingque_finish',function(){
            //通知每一个玩家定缺的花色
            self.queYiMen!.active = false;
            cc.vv.gameNetMgr.isDingQueing = false;
            self.initDingQue();
        });
    },
    
    showDingQueChoice:function(){
        this.queYiMen!.active = true;
        var sd = cc.vv.gameNetMgr.getSelfData();
        var typeCounts = [0,0,0];
        for(var i = 0; i < sd.holds.length; ++i){
            var pai = sd.holds[i];
            // getMahjongType 的声明带 undefined（越界才可能出现），老代码不判空。
            var type = cc.vv.mahjongmgr.getMahjongType(pai)!;
            typeCounts[type]++;
        }
        
        var min = 65535;
        var minIndex = 0;
        for(var i = 0; i < typeCounts.length; ++i){
            if(typeCounts[i] < min){
                min = typeCounts[i];
                minIndex = i;
            }
        }
        
        var arr = ["tong","tiao","wan"];
        for(var i = 0; i < arr.length; ++i){
            var node = this.queYiMen!.getChildByName(arr[i]);
            if(minIndex == i){
                node.getComponent(cc.Animation).play("dingque_tuijian");
            }
            else{
                node.getComponent(cc.Animation).stop();
            }
            //this.queYiMen.getChildByName(arr[i]).getChildByName('jian').active = minIndex == i;    
        }
        
        this.reset();
        for(var i = 0; i < this.tips.length; ++i){
            var n = this.tips[i];
            if(i > 0){
                n.node.active = false;                
            }
            else{
                n.node.active = true;
            }
        }
    },
    
    initDingQue:function(){
        var arr = ["tong","tiao","wan"];
        // 老代码不判空：seats 为 null 时运行期行为与迁移前一致。
        var data = cc.vv.gameNetMgr.seats!;
        for(var i = 0; i < data.length; ++i){
            // 这个局部变量老代码里先当数字用（座位上的定缺），合法时又换成花色名字符串，
            // 不合法时置 null，所以声明成联合类型。
            var que: Pai | string | null = data[i].dingque;
            if(que == null || que < 0 || que >= arr.length){
                que = null;
            }
            else{
                que = arr[que]; 
            }
            
            var localIndex = cc.vv.gameNetMgr.getLocalIndex(i);
            if(que){
                this.dingques[localIndex].getChildByName(que).active = true;    
            }
        }
    },
    
    reset:function(){
        this.setInteractable(true);
        
        this.selected.push(this.queYiMen!.getChildByName("tong_selected"));
        this.selected.push(this.queYiMen!.getChildByName("tiao_selected"));
        this.selected.push(this.queYiMen!.getChildByName("wan_selected"));
        for(var i = 0; i < this.selected.length; ++i){
            this.selected[i].active = false;
        }        
        
        for(var i = 0; i < this.dingques.length; ++i){
            for(var j = 0; j < this.dingques[i].children.length; ++j){
                this.dingques[i].children[j].active = false;    
            }
        }
    },
    
    onQueYiMenClicked:function(event: cc.Event){
        var type = 0;
        if(event.target.name == "tong"){
            type = 0;
        }
        else if(event.target.name == "tiao"){
            type = 1;
        }
        else if(event.target.name == "wan"){
            type = 2;
        }
        
        for(var i = 0; i < this.selected.length; ++i){
            this.selected[i].active = false;
        }  
        this.selected[type].active = true;
        cc.vv.gameNetMgr.dingque = type;
        cc.vv.net.send("dingque",type);
        
        //this.setInteractable(false);
    },
    
    setInteractable:function(value: boolean){
        this.queYiMen!.getChildByName("tong").getComponent(cc.Button).interactable = value;
        this.queYiMen!.getChildByName("tiao").getComponent(cc.Button).interactable = value;
        this.queYiMen!.getChildByName("wan").getComponent(cc.Button).interactable = value;        
    }

    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
});
export { };
