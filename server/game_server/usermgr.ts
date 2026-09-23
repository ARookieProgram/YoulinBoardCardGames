import * as roomMgr from "./roommgr";

import type { GameSocket, ServerPushEvent, SocketPayload } from "../types/protocol";

/**
 * `userId -> socket` 映射与推送助手。
 *
 * 对局内的推送**统一**走这里：
 * - `sendMsg(userId, event, data)`：发给单个玩家，不在线则静默丢弃；
 * - `broacastInRoom(event, data, sender, includingSender)`：广播给同房间座位
 *   （拼写就是 `broacast`，不要"顺手修正"，否则会漏掉调用点）；
 * - `kickAllInRoom(roomId)`：踢出房间内所有连接，不推送事件。
 *
 * 登录/连接阶段（此时还没有房间可广播）的那几处 `socket.emit` 是唯一例外，见 socket_service.ts。
 */

/** userId -> 连接。断开后 delete，因此值可为 undefined。 */
var userList: Record<number, GameSocket | undefined> = {};
var userOnline = 0;

/**
 * 登记一个玩家的连接（登录成功时调用）。
 *
 * @param userId 玩家 id。
 * @param socket 该玩家的连接。
 */
export function bind(userId: number, socket: GameSocket): void {
    userList[userId] = socket;
    userOnline++;
}

/**
 * 移除一个玩家的连接（断开或踢出时调用）。
 *
 * @param userId 玩家 id。
 * @param socket 原实现签名里有这个参数但从不使用，保留以维持调用点一致。
 */
export function del(userId: number, socket?: GameSocket): void {
    delete userList[userId];
    userOnline--;
}

/**
 * 取某个玩家的连接。
 *
 * @param userId 玩家 id。
 * @returns 连接；不在线则 undefined。
 */
export function get(userId: number): GameSocket | undefined {
    return userList[userId];
}

/**
 * 玩家是否在线。
 *
 * @param userId 玩家 id。
 * @returns 在线为 true。
 */
export function isOnline(userId: number): boolean {
    var data = userList[userId];
    if(data != null){
        return true;
    }
    return false;
}

/**
 * 当前在线连接数。
 *
 * @returns 在线数。
 */
export function getOnlineCount(): number {
    return userOnline;
}

/**
 * 给单个玩家推送。
 *
 * @param userId 目标玩家；不在线则静默丢弃。
 * @param event 事件名（与客户端 addHandler 逐字一致）。
 * @param msgdata 载荷。
 */
export function sendMsg(userId: number, event: ServerPushEvent, msgdata: SocketPayload): void {
    console.log(event);
    var userInfo = userList[userId];
    if(userInfo == null){
        return;
    }
    var socket = userInfo;
    if(socket == null){
        return;
    }

    socket.emit(event,msgdata);
}

/**
 * 踢出房间内所有连接（解散房间时用）。不推送任何事件。
 *
 * @param roomId 房间号。
 */
export function kickAllInRoom(roomId: string | null): void {
    if(roomId == null){
        return;
    }
    var roomInfo = roomMgr.getRoom(roomId);
    if(roomInfo == null){
        return;
    }

    for(var i = 0; i < roomInfo.seats.length; ++i){
        var rs = roomInfo.seats[i];

        //如果不需要发给发送方，则跳过
        if(rs.userId > 0){
            var socket = userList[rs.userId];
            if(socket != null){
                del(rs.userId);
                socket.disconnect();
            }
        }
    }
}

/**
 * 把事件广播给同房间的所有座位。
 *
 * @param event 事件名（与客户端 addHandler 逐字一致）。
 * @param data 载荷。
 * @param sender 发送者 userId。
 * @param includingSender 为 true 时也发给发送者自己。
 */
export function broacastInRoom(
    event: ServerPushEvent,
    data: SocketPayload,
    sender: number,
    includingSender?: boolean,
): void {
    var roomId = roomMgr.getUserRoom(sender);
    if(roomId == null){
        return;
    }
    var roomInfo = roomMgr.getRoom(roomId);
    if(roomInfo == null){
        return;
    }

    for(var i = 0; i < roomInfo.seats.length; ++i){
        var rs = roomInfo.seats[i];

        //如果不需要发给发送方，则跳过
        if(rs.userId == sender && includingSender != true){
            continue;
        }
        var socket = userList[rs.userId];
        if(socket != null){
            socket.emit(event,data);
        }
    }
}
