import assert from "node:assert/strict";
import { test } from "node:test";
import { createRequire } from "node:module";
import vm from "node:vm";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { transformSync } from "esbuild";

const require = createRequire(import.meta.url);
const root = path.resolve(import.meta.dirname, "..");
const stored = { deviceId: "device", pairing: { host: "hub", port: 19443, fingerprint: "A".repeat(64) } };
const session = { sessionId: "session", customerName: "Gamer", startedAt: new Date().toISOString(), walletBalance: 100000 };
const defer = () => {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
};

function load(file, overrides = {}, globals = {}) {
  const filename = path.join(root, "electron", file);
  const extra = file === "main.ts" ? "\nexport { AppController };" : "";
  const code = transformSync(fs.readFileSync(filename, "utf8") + extra, { loader: "ts", format: "cjs", target: "node16" }).code;
  const module = { exports: {} };
  const localRequire = (id) => {
    if (Object.hasOwn(overrides, id)) return overrides[id];
    if (id === "./logger") return { log() {}, initLogging() {} };
    if (id.startsWith(".")) return load(`${id.slice(2)}.ts`, overrides, globals);
    return require(id);
  };
  vm.runInNewContext(code, {
    module, exports: module.exports, require: localRequire, process, Buffer, console, URL,
    setTimeout, clearTimeout, setInterval, clearInterval, __dirname: path.dirname(filename), ...globals,
  }, { filename });
  return module.exports;
}

function controller(overrides = {}, globals = {}) {
  let state = { ...stored };
  const electron = { app: { setName() {}, getVersion: () => "0.2.8", getPath: () => os.tmpdir(), requestSingleInstanceLock: () => false, quit() {} } };
  const mocks = {
    electron,
    "./state-store": { StateStore: class {
      load() { return { ...state }; }
      save(next) { state = next; }
      openToken() { return "token"; }
    } },
    "./games-store": { GamesStore: class { loadGames() { return []; } } },
    ...overrides,
  };
  const { AppController } = load("main.ts", mocks, globals);
  const c = new AppController();
  c.state = { ...c.state, paired: true, phase: "connected", locked: false, userSession: { ...session } };
  c.syncKioskEnforcement = () => {};
  c.killExplorer = () => {};
  return c;
}

function connection(callback, journalPath) {
  const { EdgeConnection } = load("edge-connection.ts");
  return new EdgeConnection({
    target: stored.pairing, token: "token", deviceId: "device", appVersion: "test",
    getState: () => "LOCKED", journalPath,
    callbacks: { onCommand: callback },
  });
}

const command = (kind = "client.lock", id = "command") => ({
  command_id: id, command_type: kind, payload: {}, expires_at: new Date(Date.now() + 120000).toISOString(),
});

for (const skew of [-300000, 300000]) {
  test(`GN-01: valid command with clock skew ${skew}`, async () => {
    let calls = 0;
    const c = connection(() => { calls++; return { status: "ok" }; });
    c.serverSkewMs = skew;
    c.deliver({ ...command(), expires_at: new Date(Date.now() + skew + 120000).toISOString() });
    await c.commandQueue;
    assert.equal(calls, 1);
    assert.equal(c.completed.get("command").status, "ok");
  });
}

test("GN-08: journal survives a new connection and never repeats restart", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gn-journal-test-"));
  const file = path.join(dir, "commands.json");
  let calls = 0;
  try {
    const c = connection(() => { calls++; return { status: "ok" }; }, file);
    const cmd = command("client.restart_app");
    c.deliver(cmd);
    c.deliver(cmd);
    await c.commandQueue;
    const next = connection(() => { calls++; return { status: "ok" }; }, file);
    next.deliver(cmd);
    await next.commandQueue;
    assert.equal(calls, 1);
  } finally {
    fs.unlinkSync(file);
    fs.rmdirSync(dir);
  }
});

test("GN-22: commands are serialized until cleanup completes", async () => {
  const pending = defer();
  const seen = [];
  const c = connection(async (cmd) => {
    seen.push(cmd.command_id);
    if (cmd.command_id === "lock") await pending.promise;
    return { status: "ok" };
  });
  c.deliver(command("client.lock", "lock"));
  c.deliver(command("client.unlock", "unlock"));
  await Promise.resolve();
  assert.deepEqual(seen, ["lock"]);
  pending.resolve();
  await c.commandQueue;
  assert.deepEqual(seen, ["lock", "unlock"]);
});

test("GN-06: a late login response cannot unlock an offline client", async () => {
  const pending = defer();
  const c = controller({ "./pinned-agent": {
    getPinnedHttpsAgent() {}, requestJson: () => pending.promise, errorMessage: String,
  } });
  c.state.locked = true;
  const result = c.userLogin({ username: "gamer", password: "secret" });
  c.state.phase = "offline";
  c.sessionEpoch++;
  pending.resolve({ status: 200, body: { session_id: "old" } });
  assert.equal((await result).ok, false);
  assert.equal(c.state.locked, true);
});

test("GN-05: failed logout preserves session and returns failure", async () => {
  const c = controller({ "./pinned-agent": {
    getPinnedHttpsAgent() {}, requestJson: async () => { throw new Error("timeout"); },
    errorMessage: (error) => error.message,
  } }, { setTimeout: () => 1, clearTimeout() {} });
  c.killAllGamesAndApps = async () => {};
  const result = await c.userLogout();
  assert.equal(result.ok, false);
  assert.equal(c.state.locked, true);
  assert.equal(c.state.userSession.sessionId, "session");
  assert.equal(c.pendingLogout, "session");
});

test("GN-23 and GN-28: temporary lock and admin access retain the paid session", async () => {
  const c = controller();
  assert.equal((await c.userLogout({ keepProcesses: true })).ok, true);
  assert.equal(c.state.userSession.sessionId, "session");
  c.adminUnlock();
  assert.equal(c.state.userSession.sessionId, "session");
});

test("GN-07 and GN-17: heartbeat repairs null or different session; welcome subtracts cost", () => {
  let callbacks;
  const c = controller({ "./edge-connection": { EdgeConnection: class {
    constructor(options) { callbacks = options.callbacks; }
    start() {}
    notifyState() {}
  } } });
  c.killAllGamesAndApps = async () => {};
  c.openConnection(stored, "token");
  const sync = { session_id: "new", wallet_balance: 100000, cost: 20000, hourly_rate: 40000, elapsed_seconds: 1800 };
  callbacks.onWelcome({ session: sync });
  assert.equal(c.state.userSession.remainingBalance, 80000);
  callbacks.onHeartbeatAck({ games_hash: "no-session-field" });
  assert.equal(c.state.userSession.sessionId, "new");
  callbacks.onHeartbeatAck({ session_sync: null });
  assert.equal(c.state.userSession, null);
  assert.equal(c.state.locked, true);
  callbacks.onHeartbeatAck({ session_sync: { ...sync, session_id: "next" } });
  assert.equal(c.state.userSession.sessionId, "next");
});

test("GN-13 and GN-14: failed spawn returns failure; close removes real tracked PID", async () => {
  let child;
  const c = controller({ "node:child_process": { spawn() {
    child = new EventEmitter();
    child.pid = 42;
    child.unref = () => {};
    return child;
  } } });
  const failed = c.launchGame({ name: "test", executable: process.execPath });
  child.emit("error", new Error("ENOEXEC"));
  assert.equal((await failed).ok, false);
  const launched = c.launchGame({ name: "test", executable: process.execPath });
  child.emit("spawn");
  assert.equal((await launched).pid, 42);
  assert.equal(c.runningProcesses.length, 1);
  child.emit("close", 0);
  assert.equal(c.runningProcesses.length, 0);
  assert.equal(c.launchedGamesMap.size, 0);
});

test("GN-25: process-only fallback never sends a PID as HWND", async () => {
  const c = controller();
  c.kioskGuard.listWindows = async () => [];
  c.runningProcesses = [{ pid: 42 }];
  const apps = await c.getRunningApps();
  assert.equal(apps[0].hwnd, "");
  assert.equal(c.focusApp(apps[0].hwnd).ok, false);
});

test("GN-15: disk stream errors reject the update and release update lock", async () => {
  const { Writable } = require("node:stream");
  let stream;
  const electron = { app: { getVersion: () => "old", getPath: () => os.tmpdir() } };
  const http = { get(_url, _options, callback) {
    const req = new EventEmitter();
    req.setTimeout = () => {};
    req.destroy = (error) => req.emit("error", error);
    queueMicrotask(() => {
      stream = new PassThrough();
      stream.statusCode = 200;
      stream.headers = {};
      callback(stream);
      stream.end("package");
    });
    return req;
  } };
  const { performClientUpdate, isUpdateInProgress } = load("updater.ts", {
    electron, "node:http": http,
    "node:fs": { ...fs, existsSync: () => true, unlinkSync() {},
      createWriteStream: () => new Writable({ write(_chunk, _encoding, done) { done(new Error("ENOSPC")); } }),
    },
  });
  await assert.rejects(performClientUpdate({ version: "new", url: "http://hub/update" }), /ENOSPC/);
  assert.equal(isUpdateInProgress(), false);
});

for (const timeoutKind of ["idle", "deadline"]) {
  test(`GN-16: ${timeoutKind} timeout releases the update lock`, async () => {
    let idleTimeout, deadlineTimeout;
    const http = { get() {
      const req = new EventEmitter();
      req.setTimeout = (_ms, callback) => { idleTimeout = callback; };
      req.destroy = (error) => { if (error) req.emit("error", error); };
      return req;
    } };
    const { performClientUpdate, isUpdateInProgress } = load("updater.ts", {
      electron: { app: { getVersion: () => "old", getPath: () => os.tmpdir() } },
      "node:http": http,
    }, { setTimeout: (callback) => { deadlineTimeout = callback; return 1; }, clearTimeout() {} });
    const update = performClientUpdate({ version: "new", url: "http://hub/update" });
    (timeoutKind === "idle" ? idleTimeout : deadlineTimeout)();
    await assert.rejects(update);
    assert.equal(isUpdateInProgress(), false);
  });
}

for (const failure of ["error", "pipe", "ready-timeout"]) {
  test(`GN-21/GN-26: file-based helper startup recovers from ${failure}`, () => {
    let child, args;
    const timers = new Map();
    const { Win32KioskGuard } = load("kiosk-guard.ts", {
      "node:child_process": { spawn(_exe, argv) {
        args = argv;
        child = new EventEmitter();
        child.stdout = new PassThrough();
        child.stderr = new PassThrough();
        child.stdin = new PassThrough();
        child.kill = () => {};
        return child;
      } },
    }, {
      process: { ...process, platform: "win32" },
      setTimeout: (callback, ms) => { timers.set(ms, callback); return ms; },
      clearTimeout: (ms) => timers.delete(ms),
    });
    const guard = new Win32KioskGuard();
    let down = 0;
    guard.onWorkerDown = () => down++;
    guard.setMode("LOCK");
    assert.ok(args.includes("-File"));
    assert.ok(args.join(" ").length < 1000);
    const file = args.at(-1);
    assert.ok(fs.readFileSync(file, "utf8").includes("[GnKioskGuard]::Run(1)"));
    if (failure === "ready-timeout") timers.get(20000)();
    else if (failure === "pipe") child.stdin.emit("error", new Error("EPIPE"));
    else child.emit("error", new Error("ENOENT"));
    child.emit("close", 1);
    assert.equal(down, 1);
    assert.equal(guard.worker, null);
    assert.ok(timers.has(2000));
    assert.equal(fs.existsSync(file), false);
  });
}

test("GN-19: discovery reconnects when only the port changes", () => {
  const c = controller({ "./pinned-agent": { errorMessage: String } });
  c.state.phase = "offline";
  let next;
  c.openConnection = (target) => { next = target; };
  c.handleDiscoveredServer({ ...stored.pairing, port: 20443 });
  assert.equal(next.pairing.port, 20443);
});
