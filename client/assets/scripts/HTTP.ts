
var URL = "http://127.0.0.1:9000";

// 本模块是 CommonJS exports 文件：外部直接写 cc.vv.http.token = ...，
// 所以必须保持 exports.x = ... 的写法（改成 ESM 的 export var 会把绑定拆开、改行为）。
declare var exports: HttpModule;

/** `HttpModule` 的初始状态：`init()` 之前 `master_url` / `url` 还是 null（老代码的初始化顺序）。 */
interface HttpModuleInitState {
    master_url: string | null;
    url: string | null;
}

// 共享接口 HttpModule 把这两个字段声明成「init() 之后」的非空 string，而老代码这里先写 null；
// 这两次赋值做一次断言放宽类型，运行时写进去的仍然是 null。
(exports as HttpModuleInitState).master_url = null;
(exports as HttpModuleInitState).url = null;
exports.token = null;

init();

function init() {
    exports.master_url = URL;
    exports.url = URL;
}

function setURL(url: string) {
    URL = url;
    init();
};

function sendRequest(path: string, data: { [key: string]: unknown } | null, handler?: ((ret: HttpResp) => void) | null, extraUrl?: string | null) {
    var xhr = cc.loader.getXMLHttpRequest();
    xhr.timeout = 5000;

    if (data == null) {
        data = {};
    }
    if (exports.token) {
        data.token = exports.token;
    }

    if (extraUrl == null) {
        extraUrl = exports.url;
    }

    //解析请求路由以及格式化请求参数
    var sendpath = path;
    var sendtext = '?';
    for (var k in data) {
        if (sendtext != "?") {
            sendtext += "&";
        }
        sendtext += (k + "=" + data[k]);
    }

    //组装完整的URL
    var requestURL = extraUrl + sendpath + encodeURI(sendtext);

    //发送请求
    console.log("RequestURL:" + requestURL);
    xhr.open("GET", requestURL, true);

    if (cc.sys.isNative) {
        xhr.setRequestHeader("Accept-Encoding", "gzip,deflate", "text/html;charset=UTF-8");
    }

    var timer = setTimeout(function() {
        xhr.hasRetried = true;
        xhr.abort();
        console.log('http timeout');
        retryFunc();
    }, 5000);

    var retryFunc = function() {
        sendRequest(path, data, handler, extraUrl);
    };

    xhr.onreadystatechange = function () {
        console.log("onreadystatechange");
        clearTimeout(timer);
        if (xhr.readyState === 4 && (xhr.status >= 200 && xhr.status < 300)) {
            // console.log("http res(" + xhr.responseText.length + "):" + xhr.responseText);
            cc.log("request from [" + xhr.responseURL + "] data [", ret, "]");
            var respText = xhr.responseText;

            var ret = null;
            try {
                ret = JSON.parse(respText);
            } catch (e) {
                console.log("err:" + e);
                ret = {
                    errcode: -10001,
                    errmsg: e
                };
            }

            if (handler) {
                handler(ret);
            }

            handler = null;
        }
        else if (xhr.readyState === 4) {
            if(xhr.hasRetried){
                return;
            }

            console.log('other readystate == 4' + ', status:' + xhr.status);
            setTimeout(function() {
                retryFunc();
            }, 5000);
        }
        else {
            console.log('other readystate:' + xhr.readyState + ', status:' + xhr.status);
        }
    };

    try {
        xhr.send();
    }
    catch (e) {
        //setTimeout(retryFunc, 200);
        retryFunc();
    }

    return xhr;
}

exports.sendRequest = sendRequest;
exports.setURL = setURL;

export { };
