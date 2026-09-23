import * as http from "node:http";
import * as https from "node:https";
import * as qs from "node:querystring";

import type { Request, Response } from "express";

/**
 * HTTP 客户端 / 统一响应出口。
 *
 * 迁移前的形态是 `exports.xxx = function(...)` 的回调风格；这里保持同样的回调风格
 * （没有 Promise 化），只把回调参数换成可判别联合，好让调用方在严格模式下能安全取字段。
 */

/** URL 查询参数。客户端 `HTTP.js` 全部用 GET，参数走 query string。 */
export type QueryParams = Record<string, string | number | boolean | null | undefined>;

/** 解析后的 JSON 响应体：字段类型未知，取用时必须收窄。 */
export interface JsonObject {
  [key: string]: unknown;
}

/** `get` / `get2` 的结果：先看 `ok`，再取 `data` 或 `error`。 */
export type HttpResult = { ok: true; data: JsonObject } | { ok: false; error: Error };

/** `get` / `get2` 的回调（原实现是 `callback(ret, data)`，现改为单一结果对象）。 */
export type HttpCallback = (result: HttpResult) => void;

/** `getRaw` 的回调：失败时 contentType 为 null（原实现如此），成功时是响应头里的 content-type。 */
export type RawCallback = (
  contentType: string | undefined | null,
  body: JsonObject | string | null,
) => void;

// ---------------------------------------------------------------------------
// String.prototype.format —— 老代码的基础设施，行为逐字保留。
//
// `utils/db.ts` 里的 11 处 SQL 模板依赖它做 `{0} {1} …` 替换：
//     sql = sql.format(userId,account,name,...);
// 迁移前这段补丁写在 http.js 顶部，加载 http 模块即生效；db.ts 里显式
// `import "./http"` 把这条隐式依赖摆到明面上，避免以后有人换掉加载顺序。
// ---------------------------------------------------------------------------
String.prototype.format = function (
  this: string,
  ...args: ReadonlyArray<string | number | Record<string, string | number>>
): string {
  let result: string = this;
  if (args.length > 0) {
    const first = args[0];
    if (args.length === 1 && typeof first === "object" && first !== null) {
      for (const key of Object.keys(first)) {
        const value = first[key];
        if (value !== undefined) {
          const reg = new RegExp("({" + key + "})", "g");
          result = result.replace(reg, String(value));
        }
      }
    } else {
      for (let i = 0; i < args.length; i++) {
        const value = args[i];
        if (value !== undefined) {
          // 说明：这里刻意用 {0} {1} 这种写法而不是正则字符类，
          // 索引大于 9 时 {10} 才不会被当成 {1} + '0'（见原实现注释）。
          const reg = new RegExp("({)" + i + "(})", "g");
          result = result.replace(reg, String(value));
        }
      }
    }
  }
  return result;
};

/**
 * GET 一个 JSON 接口（按 host/port/path 组装）。
 *
 * 与 `get2` 的区别只在入参形态：这个版本让调用方分别给 host、port、path。
 *
 * @param host 目标主机。
 * @param port 目标端口（不传则用协议默认端口）。
 * @param path 路径。
 * @param data 查询参数。
 * @param callback 结果回调。
 * @param safe 为 true 时用 https。
 */
export function get(
  host: string,
  port: number | undefined,
  path: string,
  data: QueryParams,
  callback: HttpCallback,
  safe?: boolean,
): void {
  const content = qs.stringify(data);
  const options: http.RequestOptions = {
    hostname: host,
    path: path + "?" + content,
    method: "GET",
  };
  if (port) {
    options.port = port;
  }
  const proto = safe ? https : http;
  const req = proto.request(options, function (res) {
    res.setEncoding("utf8");
    res.on("data", function (chunk) {
      const json: JsonObject = JSON.parse(chunk);
      callback({ ok: true, data: json });
    });
  });

  req.on("error", function (e) {
    console.log("problem with request: " + describeError(e, host, port, path));
    callback({ ok: false, error: e });
  });

  req.end();
}

/**
 * GET 一个 JSON 接口（整条 url 由调用方给全）。
 *
 * @param url 完整 URL。
 * @param data 查询参数。
 * @param callback 结果回调。
 * @param safe 为 true 时用 https。
 */
export function get2(url: string, data: QueryParams, callback: HttpCallback, safe?: boolean): void {
  const content = qs.stringify(data);
  const fullUrl = url + "?" + content;
  const proto = safe ? https : http;
  const req = proto.get(fullUrl, function (res) {
    res.setEncoding("utf8");
    res.on("data", function (chunk) {
      const json: JsonObject = JSON.parse(chunk);
      callback({ ok: true, data: json });
    });
  });

  req.on("error", function (e) {
    console.log("problem with request: " + errorCode(e) + " — " + fullUrl);
    callback({ ok: false, error: e });
  });

  req.end();
}

/**
 * 拉取一个 URL 的原始响应体，结果通过 `callback(contentType, body)` 返回；失败时两个参数都是 null。
 *
 * 这里原先叫 `getSync()`：用 fibers 把异步 HTTP 包装成同步调用（fibers.yield / fiber.run）。
 * 但 fibers 1.0.15 的原生模块只支持到 node 8 左右，在 Node 12+ 与 Apple Silicon 上根本编译不出来，
 * `require('fibers')` 直接抛 "Missing binary"，导致三个进程连启动都做不到。
 * 因此改回与其它导出函数一致的回调风格，调用方按异步写法处理（见 account_server.ts 的 /image）。
 *
 * @param url 完整 URL。
 * @param data 查询参数。
 * @param safe 为 true 时用 https。
 * @param encoding 响应编码；传 `binary` 时不做 JSON 解析，直接把原始文本交给回调。
 * @param callback 结果回调。
 */
export function getRaw(
  url: string,
  data: QueryParams,
  safe: boolean,
  encoding: BufferEncoding | undefined,
  callback: RawCallback,
): void {
  const content = qs.stringify(data);
  // data 为空时不要拼出多余的 '?'
  const reqUrl = content ? url + "?" + content : url;

  const proto = safe ? https : http;
  const useEncoding: BufferEncoding = encoding ?? "utf8";

  // end 与 error 在异常链路上可能都会触发，保证回调只走一次
  let done = false;
  function finish(contentType: string | undefined | null, body: JsonObject | string | null): void {
    if (done) {
      return;
    }
    done = true;
    callback(contentType, body);
  }

  const req = proto.get(reqUrl, function (res) {
    res.setEncoding(useEncoding);
    let body = "";
    const type = res.headers["content-type"];

    res.on("data", function (chunk) {
      body += chunk;
    });

    res.on("end", function () {
      if (useEncoding !== "binary") {
        try {
          const json: JsonObject = JSON.parse(body);
          finish(type, json);
        } catch (e) {
          // 老实现解析失败时没有唤醒 fiber，调用方会一直挂住；现在明确按失败返回
          console.log("JSON parse error: " + String(e) + ", url: " + reqUrl);
          finish(null, null);
        }
      } else {
        finish(type, body);
      }
    });
  });

  req.on("error", function (e) {
    console.log("problem with request: " + errorCode(e) + " — " + reqUrl);
    finish(null, null);
  });

  req.end();
}

/**
 * GET 一个接口并把响应体交给回调（不解析 JSON）。
 *
 * @param host 目标主机。
 * @param port 目标端口。
 * @param path 路径。
 * @param data 查询参数。
 * @param callback 收到每个响应数据块时回调（body 文本）。
 */
export function post(
  host: string,
  port: number,
  path: string,
  data: QueryParams,
  callback: (chunk: string) => void,
): void {
  const content = qs.stringify(data);
  const options: http.RequestOptions = {
    hostname: host,
    port: port,
    path: path + "?" + content,
    method: "GET",
  };

  const req = http.request(options, function (res) {
    console.log("STATUS: " + res.statusCode);
    console.log("HEADERS: " + JSON.stringify(res.headers));
    res.setEncoding("utf8");
    res.on("data", function (chunk) {
      callback(chunk);
    });
  });

  req.on("error", function (e) {
    console.log("problem with request: " + e.message);
  });

  req.end();
}

/**
 * 大厅服与游戏服给客户端/调用方返回 JSON 的统一出口。
 *
 * 账号服没有跟进这条约定（它各自定义了本地 `send(res, ret)`），改动账号服时按它本地写法来。
 *
 * @param res express 响应对象。
 * @param errcode 业务错误码，0 表示成功。
 * @param errmsg 错误描述。
 * @param data 业务数据；会被就地写入 errcode / errmsg 后序列化。
 */
export function send(
  res: Response,
  errcode: number,
  errmsg: string,
  data: Record<string, unknown> = {},
): void {
  data.errcode = errcode;
  data.errmsg = errmsg;
  const jsonstr = JSON.stringify(data);
  res.send(jsonstr);
}

/**
 * 取 query 参数里的字符串形态。
 *
 * express 的类型把 query 值放宽成 `string | string[] | ParsedQs | ParsedQs[] | undefined`。
 * 本仓库的接口只走 `HTTP.js` 的 GET + 简单 query（见 protocol.md §3），实际拿到的永远是字符串；
 * 数组/对象一律当作"没传"——原实现会把数组一路带下去，结果同样是签名校验失败，殊途同归。
 *
 * @param req express 请求。
 * @param name 参数名。
 * @returns 参数值；不存在或不是字符串时为 undefined。
 */
export function queryString(req: Request, name: string): string | undefined {
  const value: unknown = req.query[name];
  return typeof value === "string" ? value : undefined;
}

/**
 * 取 query 参数里的整数，语义对齐原来的 `parseInt(req.query.x)`：缺参数返回 NaN。
 *
 * @param req express 请求。
 * @param name 参数名。
 * @returns 解析出的整数，缺参数或无法解析时为 NaN。
 */
export function queryInt(req: Request, name: string): number {
  return Number.parseInt(queryString(req, name) ?? "", 10);
}

/**
 * 把请求错误写成"哪台机器、哪个端口、哪个路径、什么错误"。
 *
 * 直接用 `e.message` 是不够的：Node 对 localhost 会同时尝试 ::1 与 127.0.0.1，
 * 两个都失败时抛出的是 message 为空的 AggregateError，日志里只剩 "problem with request: "，
 * 完全看不出到底连不上谁（游戏服每秒向大厅服心跳，日志会被这种空行刷屏）。
 *
 * @param e 捕获到的错误（`unknown`：Node 的 error 事件载荷没有静态保证）。
 * @param host 目标主机。
 * @param port 目标端口。
 * @param path 目标路径。
 * @returns 一行可读的错误描述。
 */
function describeError(e: unknown, host: string, port: number | undefined, path: string): string {
  const code = e instanceof Error ? errorCode(e) : "unknown error";
  return code + " — " + host + ":" + (port || "") + path;
}

/**
 * 取错误的 `code`（Node 的 errno 错误带这个字段，TypeScript 的 `Error` 里没有）。
 *
 * 原实现是 `(e && e.code) ? e.code : e.message`：优先用 `code`，没有则退回 `message`。
 *
 * @param e 捕获到的错误。
 * @returns 一行错误标识。
 */
function errorCode(e: Error): string {
  if ("code" in e) {
    const code: unknown = e.code;
    if (typeof code === "string" && code !== "") {
      return code;
    }
    if (typeof code === "number") {
      return String(code);
    }
  }
  return e.message !== "" ? e.message : "unknown error";
}
