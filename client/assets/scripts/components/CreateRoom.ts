// 创建房间：玩法选择（换三张/血战到底）、底分/自摸/番数/局数等选项与建房请求。
//
// 本文件用 ES6 class + @ccclass/@property 装饰器（Creator 2.4 的官方写法）：
// 运行时行为与迁移前的 CreateRoom.js 完全一致，只补了类型标注与动态组件查找处的断言。

const { ccclass, property } = cc._decorator;

@ccclass
export default class CreateRoom extends cc.Component {
    // foo: {
    //    default: null,
    //    url: cc.Texture2D,  // optional, default is typeof default
    //    serializable: true, // optional, default is true
    //    visible: true,      // optional, default is true
    //    displayName: 'Foo', // optional
    //    readonly: false,    // optional, default is false
    // },
    // ...
    @property _leixingxuanze: RadioButtonLike[] | null = null;
    @property _gamelist: cc.Node | null = null;
    @property _currentGame: cc.Node | null = null;

    // 运行时动态字段，不是 Creator 的序列化属性；declare 只做类型说明，没有补初始值。
    declare lastType: string | undefined;

    // use this for initialization
    onLoad() {

        this._gamelist = this.node.getChildByName('game_list');

        this._leixingxuanze = [];
        var t = this.node.getChildByName("leixingxuanze");
        for (var i = 0; i < t.childrenCount; ++i) {
            // RadioButton 是按类名取的组件，旧声明只返回 cc.Component；
            // 这里按运行期实际类型的字段（checked）做结构断言。
            var n = t.children[i].getComponent("RadioButton") as unknown as RadioButtonLike | null;
            if (n != null) {
                this._leixingxuanze.push(n);
            }
        }
    }

    onBtnBack() {
        this.node.active = false;
    }

    onBtnOK() {
        var usedTypes = ['xzdd', 'xlch'];
        var type = this.getType();
        if (usedTypes.indexOf(type) == -1) {
            return;
        }

        this.node.active = false;
        this.createRoom();
    }

    getType() {
        var type = 0;
        for (var i = 0; i < this._leixingxuanze!.length; ++i) {
            if (this._leixingxuanze![i].checked) {
                type = i;
                break;
            }
        }
        if (type == 0) {
            return 'xzdd';
        }
        else if (type == 1) {
            return 'xlch';
        }
        return 'xzdd';
    }

    getSelectedOfRadioGroup(groupRoot: string) {
        console.log(groupRoot);
        var t = this._currentGame!.getChildByName(groupRoot);

        var arr = [];
        for (var i = 0; i < t.children.length; ++i) {
            // 同 onLoad：RadioButton 的 checked 只在运行期存在。
            var n = t.children[i].getComponent("RadioButton") as unknown as RadioButtonLike | null;
            if (n != null) {
                arr.push(n);
            }
        }
        var selected = 0;
        for (var i = 0; i < arr.length; ++i) {
            if (arr[i].checked) {
                selected = i;
                break;
            }
        }
        return selected;
    }

    createRoom() {
        var self = this;
        var onCreate = function (ret: HttpResp) {
            if (ret.errcode !== 0) {
                cc.vv.wc.hide();
                //console.log(ret.errmsg);
                if (ret.errcode == 2222) {
                    cc.vv.alert!.show("提示", "钻石不足，创建房间失败!");
                }
                else {
                    cc.vv.alert!.show("提示", "创建房间失败,错误码:" + ret.errcode);
                }
            }
            else {
                cc.vv.gameNetMgr.connectGameServer(ret);
            }
        };

        var type = this.getType();
        var conf: RoomCreateConf | null = null;
        if (type == 'xzdd') {
            // constructSCMJConf 返回的对象里还没有 type（老代码随后才补上），断言只作用于类型。
            conf = this.constructSCMJConf() as RoomCreateConf;
        }
        else if (type == 'xlch') {
            conf = this.constructSCMJConf() as RoomCreateConf;
        }
        conf!.type = type;

        var data = {
            account: cc.vv.userMgr.account,
            sign: cc.vv.userMgr.sign,
            conf: JSON.stringify(conf)
        };
        console.log(data);
        cc.vv.wc.show("正在创建房间");
        cc.vv.http.sendRequest("/create_private_room", data, onCreate);
    }

    constructSCMJConf(): Omit<RoomCreateConf, "type"> {

        var wanfaxuanze = this._currentGame!.getChildByName('wanfaxuanze');
        // CheckBox 也是按类名取的组件，只能拿到 cc.Component；这里按运行期实际用到的 checked 断言。
        var huansanzhang = (wanfaxuanze.children[0].getComponent('CheckBox') as unknown as CheckBoxLike).checked;
        var jiangdui = (wanfaxuanze.children[1].getComponent('CheckBox') as unknown as CheckBoxLike).checked;
        var menqing = (wanfaxuanze.children[2].getComponent('CheckBox') as unknown as CheckBoxLike).checked;
        var tiandihu = (wanfaxuanze.children[3].getComponent('CheckBox') as unknown as CheckBoxLike).checked;

        var difen = this.getSelectedOfRadioGroup('difenxuanze');
        var zimo = this.getSelectedOfRadioGroup('zimojiacheng');
        var zuidafanshu = this.getSelectedOfRadioGroup('zuidafanshu');
        var jushuxuanze = this.getSelectedOfRadioGroup('xuanzejushu');
        var dianganghua = this.getSelectedOfRadioGroup('dianganghua');
        
        var conf = {
            difen:difen,
            zimo:zimo,
            jiangdui:jiangdui,
            huansanzhang:huansanzhang,
            zuidafanshu:zuidafanshu,
            jushuxuanze:jushuxuanze,
            dianganghua:dianganghua,
            menqing:menqing,
            tiandihu:tiandihu,   
        };
        // 共享声明 RoomCreateConf 把 huansanzhang / jiangdui / menqing / tiandihu 写成了 number，
        // 而老代码这四项来自 CheckBox.checked（boolean），发给服务端的始终是布尔值；
        // 这里只做类型断言，运行期内容与迁移前一致。
        return conf as unknown as Omit<RoomCreateConf, "type">;
    }

    // called every frame, uncomment this function to activate update callback
    update(dt: number = 0) {

        var type = this.getType();
        if (this.lastType != type) {
            this.lastType = type;
            for (var i = 0; i < this._gamelist!.childrenCount; ++i) {
                this._gamelist!.children[i].active = false;
            }

            var game = this._gamelist!.getChildByName(type);
            if (game) {
                game.active = true;
            }
            this._currentGame = game;
        }
    }
}

/** `RadioButton`（尚未迁移成 .ts）在本组件里被读到的字段。 */
interface RadioButtonLike {
    checked: boolean;
}

/** `CheckBox`（`CheckBox.ts`）在本组件里被读到的字段。 */
interface CheckBoxLike {
    checked: boolean;
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = CreateRoom;
