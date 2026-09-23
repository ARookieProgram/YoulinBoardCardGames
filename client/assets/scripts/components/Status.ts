/** creator.d.ts 里 Color 的构造签名没有参数，这里补一个本文件用的构造类型（只影响类型检查）。 */
interface ColorConstructor {
    new (r?: number, g?: number, b?: number, a?: number): cc.Color;
}

const { ccclass, property } = cc._decorator;

@ccclass
export default class Status extends cc.Component {
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
    @property _status: cc.Node | null = null;

    // 运行时动态字段（start() 里才赋值），没有补初始值。
    declare red: cc.Color | undefined;
    declare green: cc.Color | undefined;
    declare yellow: cc.Color | undefined;

    // use this for initialization
    start() {
        this._status = cc.find('Canvas/status');

        this.red = new (cc.Color as ColorConstructor)(205,0,0);
        this.green = new (cc.Color as ColorConstructor)(0,205,0);
        this.yellow = new (cc.Color as ColorConstructor)(255,200,0);
    }

    // called every frame, uncomment this function to activate update callback
    update(dt: number = 0) {
        var delay = this._status!.getChildByName('delay');
        if(cc.vv.net.delayMS != null){
            delay.getComponent(cc.Label).string = cc.vv.net.delayMS + 'ms';
            if(cc.vv.net.delayMS > 800){
                delay.color = this.red!;
            }
            else if(cc.vv.net.delayMS > 300){
                delay.color = this.yellow!;
            }
            else{
                delay.color = this.green!;
            }
        }
        else{
            delay.getComponent(cc.Label).string = 'N/A';
            delay.color = this.red!;
        }
        
        var power = this._status!.getChildByName('power');
        power.scaleX = cc.vv.anysdkMgr.getBatteryPercent();
    }
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = Status;
