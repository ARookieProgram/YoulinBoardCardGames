const { ccclass, property } = cc._decorator;

@ccclass
export default class CreateRole extends cc.Component {
    // 老代码是简写 `inputName: cc.EditBox`：引擎会把它规范化成 { default: null, type: cc.EditBox }
    //（见引擎 preprocess-class.js 的 getFullFormOfProperty）。这里用 @property({type: cc.EditBox}) + 初值 null
    // 写出同一个元数据，`this.inputName` 的类型与运行时行为一字未变。
    @property({type: cc.EditBox}) inputName: cc.EditBox | null = null as cc.EditBox | null;
    // foo: {
    //    default: null,
    //    url: cc.Texture2D,  // optional, default is typeof default
    //    serializable: true, // optional, default is true
    //    visible: true,      // optional, default is true
    //    displayName: 'Foo', // optional
    //    readonly: false,    // optional, default is false
    // },
    // ...

    onRandomBtnClicked(){
        var names = [
            "上官",
            "欧阳",
            "东方",
            "端木",
            "独孤",
            "司马",
            "南宫",
            "夏侯",
            "诸葛",
            "皇甫",
            "长孙",
            "宇文",
            "轩辕",
            "东郭",
            "子车",
            "东阳",
            "子言",
        ];
        
        var names2 = [
            "雀圣",
            "赌侠",
            "赌圣",
            "稳赢",
            "不输",
            "好运",
            "自摸",
            "有钱",
            "土豪",
        ];
        var idx = Math.floor(Math.random() * (names.length - 1));
        var idx2 = Math.floor(Math.random() * (names2.length - 1));
        this.inputName!.string = names[idx] + names2[idx2];
    }

    // use this for initialization
    onLoad() {
        cc.vv.utils.setFitSreenMode();
        this.onRandomBtnClicked();
    }

    onBtnConfirmClicked(){
        var name = this.inputName!.string;
        if(name == ""){
            console.log("invalid name.");
            return;
        }
        console.log(name);
        cc.vv.userMgr.create(name);
    }
    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = CreateRole;
