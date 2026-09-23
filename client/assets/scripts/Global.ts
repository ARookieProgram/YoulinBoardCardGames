var Global = cc.Class({
    extends: cc.Component,
    // 这些静态字段就是 cc.vv.global（GlobalClass）的全部成员；断言只作用于类型，
    // 运行时仍是一个普通对象字面量，字段与初值一个都没动。
    statics: {
        isstarted:false,
        netinited:false,
        userguid:0,
        nickname:"",
        money:0,
        lv:0,
        roomId:0,
    } as GlobalClass,
});

export { };
