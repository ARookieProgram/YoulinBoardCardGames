/**
 * Socket.IO protocol consistency verification.
 *
 * The client and server are two independently edited codebases that share one
 * event vocabulary, and nothing in the toolchain links them. A renamed event is
 * therefore a silent production failure: the server keeps broadcasting into the
 * void and the client keeps waiting for a message that never arrives. Both
 * directions are checked here.
 *
 * Server side: the game server never calls `socket.emit` inline. It routes every
 * push through the helpers in `game_server/usermgr.js`
 * (`sendMsg`, `broacastInRoom`) or emits directly on the login socket in
 * `game_server/socket_service.js`.
 *
 * Client side: every incoming event must be registered through
 * `cc.vv.net.addHandler('<event>', fn)`.
 */

import { readFile } from "node:fs/promises";
import { join } from "node:path";

/**
 * Event names that socket.io owns on the client connection itself rather than
 * events the game server pushes.
 */
const CLIENT_LOCAL_EVENTS = new Set(["disconnect", "connect", "reconnect", "connect_failed"]);

/**
 * Events the client registers but no server push currently sends.
 *
 * `push_need_create_role` is a leftover: it is only referenced by the client
 * handler, so it can never fire. It is listed rather than deleted because
 * removing a registered handler changes login behaviour and is a product
 * decision, not a tooling one.
 */
const KNOWN_UNSENT = new Set(["push_need_create_role"]);

/**
 * Extract the socket event vocabulary declared by the server.
 *
 * The game server never calls `socket.emit` on room sockets inline: every push
 * goes through `userMgr.sendMsg` / `userMgr.broacastInRoom`, while the login
 * socket emits directly. Both quote styles are accepted because the two copies
 * of the game manager (`gamemgr_xlch`, `gamemgr_xzdd`) do not agree on style.
 *
 * @param {string} source text of one server file.
 * @returns {Set<string>} event names.
 */
export function extractServerEvents(source) {
  const events = new Set();
  const patterns = [
    /broacastInRoom\(\s*['"]([A-Za-z0-9_]+)['"]/g,
    /sendMsg\([^,]+,\s*['"]([A-Za-z0-9_]+)['"]/g,
    /emit\(\s*['"]([A-Za-z0-9_]+)['"]/g,
  ];
  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) events.add(match[1]);
  }
  return events;
}

/**
 * Extract the socket event vocabulary the client listens for.
 *
 * Two registration paths exist and both must be counted: the game events go
 * through `cc.vv.net.addHandler('<event>', fn)`, while Net.js attaches a few
 * transport-level listeners straight to the socket with `sio.on('<event>', fn)`.
 * Missing the second path reports a false protocol break for `game_pong`, which
 * is the heartbeat the server answers.
 *
 * @param {string} source text of one client file.
 * @returns {Set<string>} event names.
 */
export function extractClientHandlers(source) {
  const events = new Set();
  const patterns = [/addHandler\(\s*['"]([A-Za-z0-9_]+)['"]/g, /sio\.on\(\s*['"]([A-Za-z0-9_]+)['"]/g];
  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) events.add(match[1]);
  }
  return events;
}

/**
 * Compare the two vocabularies.
 * @param {Set<string>} serverEvents events the server pushes.
 * @param {Set<string>} clientEvents events the client handles.
 * @returns {{ unhandled: string[], unsent: string[] }} sorted, filtered drift.
 */
export function diffProtocol(serverEvents, clientEvents) {
  const unhandled = [...serverEvents].filter((event) => !clientEvents.has(event)).sort();
  const unsent = [...clientEvents]
    .filter(
      (event) =>
        !serverEvents.has(event) && !CLIENT_LOCAL_EVENTS.has(event) && !KNOWN_UNSENT.has(event),
    )
    .sort();
  return { unhandled, unsent };
}

/**
 * Return the body of the first `##` section whose heading starts with `prefix`,
 * stopping at the next `## `.
 *
 * Matched by prefix so the heading may carry a changing count (for example
 * `## 1. 服务端推送事件（39 个）`) without silently disabling the check.
 *
 * @param {string} markdown full document.
 * @param {string} prefix heading prefix without the leading hashes.
 * @returns {string} section body, or an empty string when no heading matches.
 */
export function section(markdown, prefix) {
  const lines = markdown.split("\n");
  const start = lines.findIndex(
    (line) => line.startsWith("## ") && line.slice(3).trim().startsWith(prefix),
  );
  if (start === -1) return "";
  const rest = lines.slice(start + 1);
  const end = rest.findIndex((line) => line.startsWith("## "));
  return (end === -1 ? rest : rest.slice(0, end)).join("\n");
}

/**
 * Extract the event names documented in the server-push table of a reference
 * document.
 *
 * Scoped to one section on purpose: the document has several tables, and only the
 * server-push one is required to mirror `extractServerEvents`. Reading the whole
 * file would pull in the client→server table and report false drift. Only rows
 * whose first cell is a single backticked identifier are counted, so prose and
 * code fences are ignored.
 *
 * @param {string} markdown contents of the protocol reference document.
 * @returns {Set<string>} documented push event names.
 */
export function extractDocumentedEvents(markdown) {
  const events = new Set();
  for (const line of section(markdown, "1. 服务端推送事件").split("\n")) {
    const row = /^\|\s*`([a-z0-9_]+)`\s*\|/.exec(line);
    if (row) events.add(row[1]);
  }
  return events;
}

/**
 * Run the protocol check over the repository.
 *
 * Two independent things are verified: that the two source trees agree with each
 * other, and that the reference document's push table agrees with the server. The
 * second was added after an audit found the table had drifted from the source
 * with nothing to detect it — a stale protocol table is worse than none, because
 * it reads as authoritative.
 *
 * @param {string} root repository root.
 * @param {string[]} serverFiles server `.js` files to scan.
 * @param {string[]} clientFiles client `.js` files to scan.
 * @param {string} [referencePath] protocol reference document to cross-check.
 * @returns {Promise<{ ok: boolean, serverCount: number, clientCount: number, unhandled: string[], unsent: string[], undocumented: string[], stale: string[] }>}
 */
export async function checkProtocol(root, serverFiles, clientFiles, referencePath) {
  const serverEvents = new Set();
  for (const file of serverFiles) {
    const source = await readFile(file, "utf8");
    for (const event of extractServerEvents(source)) serverEvents.add(event);
  }

  const clientEvents = new Set();
  for (const file of clientFiles) {
    const source = await readFile(file, "utf8");
    for (const event of extractClientHandlers(source)) clientEvents.add(event);
  }

  const { unhandled, unsent } = diffProtocol(serverEvents, clientEvents);

  let undocumented = [];
  let stale = [];
  if (referencePath !== undefined) {
    const markdown = await readFile(referencePath, "utf8");
    const documented = extractDocumentedEvents(markdown);
    undocumented = [...serverEvents].filter((event) => !documented.has(event)).sort();
    stale = [...documented].filter((event) => !serverEvents.has(event)).sort();
  }

  return {
    ok: unhandled.length === 0 && unsent.length === 0 && undocumented.length === 0 && stale.length === 0,
    serverCount: serverEvents.size,
    clientCount: clientEvents.size,
    unhandled,
    unsent,
    undocumented,
    stale,
  };
}

export { join };
