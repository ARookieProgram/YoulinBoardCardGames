const { ccclass } = cc._decorator;

@ccclass
export default class Global extends cc.Component {
    static isstarted: boolean = false;
    static netinited: boolean = false;
    static userguid: number = 0;
    static nickname: string = "";
    static money: number = 0;
    static lv: number = 0;
    static roomId: number = 0;
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = Global;
