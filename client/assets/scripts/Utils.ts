cc.Class({
    extends: cc.Component,

    properties: {
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
    },

    addClickEvent:function(node: cc.Node,target: cc.Component,component: string,handler: string){
        console.log(component + ":" + handler);
        var eventHandler = new cc.Component.EventHandler();
        // creator.d.ts 把 EventHandler.target 声明成 cc.Node，而本项目老代码一律传组件进来；
        // 这里断言只作用于类型，运行时赋上去的还是这个组件对象。
        eventHandler.target = target as unknown as cc.Node;
        eventHandler.component = component;
        eventHandler.handler = handler;

        // creator.d.ts 的 getComponent 只声明了返回 cc.Component 的重载，这里断言成实际取到的组件类型。
        var clickEvents = (node.getComponent(cc.Button) as cc.Button).clickEvents;
        clickEvents.push(eventHandler);
    },
    
    addSlideEvent:function(node: cc.Node,target: cc.Component,component: string,handler: string){
        var eventHandler = new cc.Component.EventHandler();
        // 同上：EventHandler.target 的声明与老代码的用法不一致，断言只作用于类型。
        eventHandler.target = target as unknown as cc.Node;
        eventHandler.component = component;
        eventHandler.handler = handler;

        // getComponent 的返回值在 creator.d.ts 里是 cc.Component，这里断言成 cc.Slider。
        var slideEvents = (node.getComponent(cc.Slider) as cc.Slider).slideEvents;
        slideEvents.push(eventHandler);
    },

    addEscEvent:function(node: cc.Node){
        cc.eventManager.addListener({
            event: cc.EventListener.KEYBOARD,
            onKeyPressed:  function(keyCode: number, event: cc.Event){
            },
            onKeyReleased: function(keyCode: number, event: cc.Event){
                if(keyCode == cc.KEY.back){
                    // 共享声明 AlertBox.show 只写了 3 个形参，Alert.js 的 show 实际是 4 个
                    //（第 4 个是「是否需要取消按钮」）；老代码这里传了 true，断言补上第 4 个形参，运行时不变。
                    (cc.vv.alert! as AlertBoxWithCancel).show('提示','确定要退出游戏吗？',function(){
                        cc.game.end();
                    },true);
                }
            }
        }, node);
    },

    setFitSreenMode:function(){
        var node = cc.find('Canvas');
        var size = cc.view.getFrameSize();
        var w = size.width;
        var h = size.height;
    
        // getComponent 的返回值在 creator.d.ts 里是 cc.Component，这里断言成 cc.Canvas。
        var cvs = node.getComponent(cc.Canvas) as cc.Canvas;
        var dw = cvs.designResolution.width;
        var dh = cvs.designResolution.height;
        //如果更宽 则让高显示满
        if((w / h)  > (dw / dh)){
            cvs.fitHeight = true;
            cvs.fitWidth = false;
        }
        else{
            //如果更高，则让宽显示满
            cvs.fitHeight = false;
            cvs.fitWidth = true;
        }
    }

    // called every frame, uncomment this function to activate update callback
    // update: function (dt) {

    // },
});

/** `AlertBox.show` 的完整签名：`Alert.js` 的 `show(title, content, onok, needcancel)` 一共 4 个形参。 */
interface AlertBoxWithCancel {
    show(title: string, msg: string, callback?: () => void, needcancel?: boolean): void;
}

export { };
