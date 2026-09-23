const { ccclass, property } = cc._decorator;

@ccclass
export default class LoadingLogic extends cc.Component {
    @property(cc.Label) tipLabel: cc.Label | null = null;
    @property _stateStr: string = '';
    @property _progress: number = 0.0;
    // 老代码里没有用到这个字段，也没有任何赋值，类型无从判断，按 unknown 声明。
    @property _splash: unknown = null;
    @property _isLoading: boolean = false;

    // use this for initialization
    onLoad() {
        cc.vv.utils.setFitSreenMode();
        this.tipLabel!.string = this._stateStr;
        this.startPreloading();
    }

    startPreloading(){
        this._stateStr = "正在加载资源，请稍候"
        this._isLoading = true;
        var self = this;
        
        var onProgress = function ( completedCount: number, totalCount: number,  item: unknown ){
            //console.log("completedCount:" + completedCount + ",totalCount:" + totalCount );
            if(self._isLoading){
                self._progress = completedCount/totalCount;
            }
        };
        
        //cc.loader.loadResDir("textures",cc.Texture2D, onProgress,function (err, assets) {
        //    self.onLoadComplete();
        //});
        self.onLoadComplete();      
    }

    onLoadComplete(){
        this._isLoading = false;
        this._stateStr = "准备登陆";
        cc.director.loadScene("login");
    }

    // called every frame, uncomment this function to activate update callback
    update(dt: number = 0) {
        if(this._stateStr.length == 0){
            return;
        }
        this.tipLabel!.string = this._stateStr + ' ';
        if(this._isLoading){
            this.tipLabel!.string += Math.floor(this._progress * 100) + "%";   
        }
        else{
            var t = Math.floor(Date.now() / 1000) % 4;
            for(var i = 0; i < t; ++ i){
                this.tipLabel!.string += '.';
            }            
        }
    }
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = LoadingLogic;
