// Socket.IO 连接、心跳与事件分发。字段全在 statics 上，所以 cc.vv.net 是**类本身**（不要 new）。
//
// 老写法用 `cc.Class({ statics: {...} })` + 手写 `this: NetClass` 给静态方法补类型；
// 现在是普通 ES6 class + `static` 成员，`this` 就是类对象（`typeof Net`），不需要再手写。

if(window.io == null){
    // socket-io 是 vendored 的 CommonJS 模块（3rdparty/socket-io.js），require 的返回值是动态边界：
    // 这里断言成 socket.io 客户端类型，运行时拿到的就是它。
    window.io = require("socket-io") as SocketIOClient;
}

const { ccclass } = cc._decorator;

@ccclass
export default class Net extends cc.Component {
    static ip: string = "";
    static sio: SocketIOSocket | null = null;
    static isPinging: boolean = false;
    static fnDisconnect: (() => void) | null = null;
    static handlers: { [event: string]: NetHandler } = {};

    // 以下三项原来的 statics 里就没有，是运行时动态字段，所以用 declare 只声明类型、不产生运行时代码。
    declare static delayMS: number | null | undefined;
    declare static lastSendTime: number | undefined;
    declare static lastRecieveTime: number | undefined;

    static addHandler(event: string, fn: NetHandler){
        if(this.handlers[event]){
            console.log("event:" + event + "' handler has been registered.");
            return;
        }

        var handler = function(data: unknown){
            //console.log(event + "(" + typeof(data) + "):" + (data? data.toString():"null"));
            if(event != "disconnect" && typeof(data) == "string"){
                data = JSON.parse(data);
            }
            fn(data);
        };
        
        this.handlers[event] = handler; 
        if(this.sio){
            console.log("register:function " + event);
            this.sio.on(event,handler);
        }
    }

    static connect(fnConnect: (data: unknown) => void,fnError: () => void) {
        var self = this;
        
        var opts = {
            'reconnection':false,
            'force new connection': true,
            'transports':['websocket', 'polling']
        }
        this.sio = window.io.connect(this.ip,opts);
        this.sio.on('reconnect',function(){
            console.log('reconnection');
        });
        this.sio.on('connect',function(data){
            self.sio!.connected = true;
            fnConnect(data);
        });
        
        this.sio.on('disconnect',function(data){
            console.log("disconnect");
            self.sio!.connected = false;
            self.close();
        });
        
        this.sio.on('connect_failed',function (){
            console.log('connect_failed');
        });
        
        for(var key in this.handlers){
            var value = this.handlers[key];
            if(typeof(value) == "function"){
                if(key == 'disconnect'){
                    // 共享接口把 fnDisconnect 声明成无参回调，老代码在这里直接赋这个 handler
                    //（close() 里也是无参调用它），断言只作用于类型，运行时不变。
                    this.fnDisconnect = value as () => void;
                }
                else{
                    console.log("register:function " + key);
                    this.sio!.on(key,value);                        
                }
            }
        }
        
        this.startHearbeat();
    }
    
    static startHearbeat(){
        // 心跳注册时 socket 必然已经建立（老代码本来就不判空），这里只做一次类型收窄；
        // 保留 `sio.on(` 这个写法，protocol 检查器按它收集客户端事件名。
        var sio = this.sio as SocketIOSocket;
        sio.on('game_pong',function(){
            console.log('game_pong');
            self.lastRecieveTime = Date.now();
            self.delayMS = self.lastRecieveTime! - self.lastSendTime!;
            console.log(self.delayMS);
        });
        this.lastRecieveTime = Date.now();
        var self = this;
        console.log(1);
        if(!self.isPinging){
            self.isPinging = true;
            cc.game.on(cc.game.EVENT_HIDE,function(){
                self.ping();
            });
            setInterval(function(){
                if(self.sio){
                    self.ping();                
                }
            }.bind(this),5000);
            setInterval(function(){
                if(self.sio){
                    if(Date.now() - self.lastRecieveTime! > 10000){
                        self.close();
                    }         
                }
            }.bind(this),500);
        }   
    }

    static send(event: string,data?: unknown){
        if(this.sio!.connected){
            if(data != null && (typeof(data) == "object")){
                data = JSON.stringify(data);
                //console.log(data);              
            }
            if(data == null){
                data = '';
            }
            // 到这里 data 只可能是字符串（对象已被 JSON.stringify、null 已换成空串），
            // 断言只为匹配 emit 的签名，运行时传的还是这个值。
            this.sio!.emit(event,data as string);                
        }
    }
    
    static ping(){
        if(this.sio){
            this.lastSendTime = Date.now();
            this.send('game_ping');
        }
    }
    
    static close(){
        console.log('close');
        this.delayMS = null;
        if(this.sio && this.sio.connected){
            this.sio.connected = false;
            this.sio.disconnect();
        }
        this.sio = null;
        if(this.fnDisconnect){
            this.fnDisconnect();
            this.fnDisconnect = null;
        }
    }
    
    static test(fnResult: (ok: boolean) => void){
        var fn = function(ret: HttpResp){
            fnResult(ret.errcode == 0);
        }
        cc.vv.http.sendRequest("/hi",null,fn,'http://' + this.ip);
    }
}

// Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
// export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
module.exports = Net;
