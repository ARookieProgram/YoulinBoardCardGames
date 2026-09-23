// Socket.IO 连接、心跳与事件分发。字段全在 statics 上，所以 cc.vv.net 是**类本身**（不要 new）；
// 静态方法里的 `this` 是类对象，按 types/cc-class.d.ts 的说明手写 `this: NetClass`。
//
// 心跳注册时 socket 必然已经建立（老代码本来就不判空），这里用交叉类型表达，
// 免得在调用点插入非空断言：写成 `sio!.on(` 会让 protocol 检查器漏掉 `game_pong` 这个事件名。
type NetClassWithSocket = NetClass & { sio: SocketIOSocket };

if(window.io == null){
    // socket-io 是 vendored 的 CommonJS 模块（3rdparty/socket-io.js），require 的返回值是动态边界：
    // 这里断言成 socket.io 客户端类型，运行时拿到的就是它。
    window.io = require("socket-io") as SocketIOClient;
}
 
var Global = cc.Class({
    extends: cc.Component,
    // 这些静态字段就是 cc.vv.net（NetClass）的全部成员；断言只作用于类型，
    // 运行时仍是一个普通对象字面量，字段与初值一个都没动。
    statics: {
        ip:"",
        sio:null,
        isPinging:false,
        fnDisconnect:null,
        handlers:{},
        addHandler:function(this: NetClass,event: string,fn: NetHandler){
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
        },
        connect:function(this: NetClass,fnConnect: (data: unknown) => void,fnError: () => void) {
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
        },
        
        startHearbeat:function(this: NetClassWithSocket){
            this.sio.on('game_pong',function(){
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
        },
        send:function(this: NetClass,event: string,data?: unknown){
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
        },
        
        ping:function(this: NetClass){
            if(this.sio){
                this.lastSendTime = Date.now();
                this.send('game_ping');
            }
        },
        
        close:function(this: NetClass){
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
        },
        
        test:function(this: NetClass,fnResult: (ok: boolean) => void){
            var fn = function(ret: HttpResp){
                fnResult(ret.errcode == 0);
            }
            cc.vv.http.sendRequest("/hi",null,fn,'http://' + this.ip);
        }
    } as NetClass,
});

export { };
