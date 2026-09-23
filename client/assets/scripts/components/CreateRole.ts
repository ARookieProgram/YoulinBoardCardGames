cc.Class({
    extends: cc.Component,

    properties: {
        // 老代码是简写 `inputName: cc.EditBox`：引擎会把它规范化成 { default: null, type: cc.EditBox }
        // （见引擎 preprocess-class.js 的 getFullFormOfProperty）。这里写成完整写法只是为了在类型层面
        // 让 `this.inputName` 拿到 EditBox 实例类型，属性的值与运行时行为一字未变。
        inputName:{ default: null as cc.EditBox | null, type: cc.EditBox },
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
    
    onRandomBtnClicked:function(){
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
    },

    // use this for initialization
    onLoad: function () {
        cc.vv.utils.setFitSreenMode();
        this.onRandomBtnClicked();
    },

    onBtnConfirmClicked:function(){
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
});

export { };
