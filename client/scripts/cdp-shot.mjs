import { writeFileSync } from "node:fs";
import WebSocket from "ws";

/**
 * Dev-only capture/inspect helper. Requires Electron started with
 * --remote-debugging-port=9223 (see dev notes); never used in production.
 *
 *   node scripts/cdp-shot.mjs shot /tmp/opencode/locked.png
 *   node scripts/cdp-shot.mjs eval "document.title"
 */

const endpoint = process.env.CDP_URL || "http://127.0.0.1:9223/json";
const [, , command, ...args] = process.argv;

const targets = await (await fetch(endpoint)).json();
const page = targets.find((target) => target.type === "page");
if (!page?.webSocketDebuggerUrl) {
  console.error("no Electron page target found on", endpoint);
  process.exit(1);
}

const socket = new WebSocket(page.webSocketDebuggerUrl, { maxPayload: 64 * 1024 * 1024 });
await new Promise((resolve, reject) => {
  socket.once("open", resolve);
  socket.once("error", reject);
});

let nextId = 0;
const pending = new Map();
socket.on("message", (raw) => {
  const message = JSON.parse(raw.toString("utf8"));
  if (message.id && pending.has(message.id)) {
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(message.error.message));
    else resolve(message.result);
  }
});

function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++nextId;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}

try {
  if (command === "shot") {
    await send("Page.enable");
    const { data } = await send("Page.captureScreenshot", {
      format: "png",
      fromSurface: true,
    });
    const output = args[0] || "/tmp/opencode/shot.png";
    writeFileSync(output, Buffer.from(data, "base64"));
    console.log(`saved ${output}`);
  } else if (command === "eval") {
    const result = await send("Runtime.evaluate", {
      expression: args.join(" "),
      returnByValue: true,
      awaitPromise: true,
    });
    console.log(JSON.stringify(result.result?.value ?? result.result, null, 2));
  } else if (command === "click") {
    const x = Number(args[0]);
    const y = Number(args[1]);
    for (const type of ["mousePressed", "mouseReleased"]) {
      await send("Input.dispatchMouseEvent", {
        type,
        x,
        y,
        button: "left",
        clickCount: 1,
      });
    }
    console.log(`clicked ${x},${y}`);
  } else if (command === "text") {
    await send("Input.insertText", { text: args.join(" ") });
    console.log("typed text");
  } else if (command === "key") {
    const key = args[0];
    for (const type of ["rawKeyDown", "keyUp"]) {
      await send("Input.dispatchKeyEvent", { type, key, windowsVirtualKeyCode: 13 });
    }
    console.log(`pressed ${key}`);
  } else {
    console.error("usage: cdp-shot.mjs <shot|eval> [...]");
    process.exitCode = 2;
  }
} finally {
  socket.close();
}
