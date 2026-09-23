const { ccclass, property } = cc._decorator;

@ccclass
export default class ReConnect extends cc.Component {
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
    // 老代码里没有用到这个字段，也没有任何赋值，类型无从判断，按 unknown 声明。
    @property _lblTip: unknown = null;
    @property _lastPing: number = 0;

    // use this for initialization
    onLoad() {
        var self = this;

        var fnTestServerOn = function () {
            cc.vv.net.test(function (ret) {
                if (ret) {
                    cc.vv.gameNetMgr.reset();
                    //cc.director.loadScene('hall');
                    var roomId = cc.vv.userMgr.oldRoomId;
                    if (roomId != null) {
                        cc.vv.userMgr.oldRoomId = null;
                        cc.vv.userMgr.enterRoom(roomId, function (ret) {
                            if (ret.errcode != 0) {
                                cc.vv.gameNetMgr.roomId = null;
                                cc.director.loadScene('hall');
                            }
                        });
                    }
                }
                else {
                    setTimeout(fnTestServerOn, 3000);
                }
            });
        }

        var fn = function (data: unknown) {
            self.node.off('disconnect', fn);
            cc.vv.wc.show("正在重连...");
            fnTestServerOn();
        };
        console.log("adasfdasdfsdf");

        this.node.on('login_finished', function () {
            cc.vv.wc.hide();
            self.node.on('disconnect', fn);
        });
        this.node.on('disconnect', fn);
    }

    // called every frame, uncomment this function to activate update callback
    update(dt: number = 0) {
    }
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = ReConnect;
