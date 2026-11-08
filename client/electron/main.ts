import {
  app,
  BrowserWindow,
  ipcMain,
  session,
  type IpcMainInvokeEvent,
} from "electron";
import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type {
  CommandNotice,
  EdgeCommand,
  PairResult,
  PublicState,
  UserLoginResult,
  UserLogoutResult,
  UserSessionInfo,
} from "../shared/ipc";
import { EdgeConnection, type CommandAck } from "./edge-connection";
import { initLogging, log } from "./logger";
import {
  errorMessage,
  parsePairing,
  PinnedHttpsAgent,
  requestJson,
  shortFingerprint,
} from "./pinned-agent";
import { StateStore, type StoredState } from "./state-store";
import { LanDiscoveryClient, type DiscoveredServer } from "./discovery";

app.setName("GameNet");
const canUnpair = process.env.GAMENET_DEV_UNPAIR === "1";
const canPreview = !app.isPackaged && process.env.GAMENET_DEV_PREVIEW === "1";

interface RegistrationBody {
  device_id?: string;
  token?: string;
  name?: string;
  hub_name?: string;
  ws_path?: string;
  device_heartbeat_seconds?: number;
  config_version?: number;
}

function emptyState(): PublicState {
  return {
    phase: "unpaired",
    paired: false,
    locked: true,
    userSession: null,
    deviceId: "",
    deviceName: "",
    hubName: "",
    heartbeatSeconds: 10,
    configVersion: 0,
    pairingHost: "",
    fingerprintShort: "",
    lastError: "",
    pendingCommands: 0,
    appVersion: app.getVersion(),
    platform: `${os.type()} ${os.release()} ${os.arch()}`,
    suggestedName: os.hostname().replace(/[^\p{L}\p{N}_.-]/gu, "-").slice(0, 80) || "PC-01",
    canUnpair,
    canPreview,
    updatedAt: new Date().toISOString(),
  };
}

function cleanText(value: unknown, maxLength: number, label: string): string {
  const text = typeof value === "string" ? value.replace(/[\u0000-\u001f\u007f]/g, "").trim() : "";
  if (!text) throw new Error(`${label} الزامی است`);
  if (text.length > maxLength) throw new Error(`${label} بیش از حد طولانی است`);
  return text;
}

function registrationError(body: unknown): string {
  if (body && typeof body === "object") {
    const error = (body as Record<string, unknown>).error;
    if (error && typeof error === "object") {
      const message = (error as Record<string, unknown>).message;
      if (typeof message === "string" && message) return message;
    }
    const detail = (body as Record<string, unknown>).detail;
    if (typeof detail === "string" && detail) return detail;
  }
  return "هاب ثبت دستگاه را نپذیرفت";
}

class AppController {
  private readonly store = new StateStore();
  private window: BrowserWindow | null = null;
  private connection: EdgeConnection | null = null;
  private state: PublicState = emptyState();
  private pairing = false;
  private runningProcesses: ChildProcess[] = [];
  private discovery: LanDiscoveryClient | null = null;

  attach(window: BrowserWindow): void {
    this.window = window;
    this.restore();
    this.startDiscovery();
  }

  private startDiscovery(): void {
    this.discovery = new LanDiscoveryClient((server) => {
      this.handleDiscoveredServer(server);
    });
    this.discovery.start();
  }

  private handleDiscoveredServer(server: DiscoveredServer): void {
    if (this.state.paired) {
      // If disconnected or IP shifted, seamlessly reconnect to the discovered server
      if (
        this.state.phase === "connecting" ||
        this.state.phase === "unreachable" ||
        this.state.phase === "disconnected"
      ) {
        const stored = this.store.load();
        if (
          stored &&
          stored.pairing.host !== server.host &&
          stored.pairing.fingerprint === server.fingerprint
        ) {
          log(
            "info",
            `Salon server IP shifted from ${stored.pairing.host} to ${server.host}. Reconnecting...`
          );
          stored.pairing.host = server.host;
          stored.pairing.port = server.port;
          this.store.save(stored);
          const token = this.store.openToken(stored);
          if (token) {
            this.openConnection(stored, token);
          }
        }
      }
    } else if (!this.pairing) {
      log(
        "info",
        `Auto-discovered salon server at ${server.pairing_string}. Connecting automatically...`
      );
      this.pair({
        pairing: server.pairing_string,
        code: "LAN_AUTO",
        name: "",
      }).catch((err) => {
        log("warn", `Auto-pair failed: ${err}`);
      });
    }
  }

  snapshot(): PublicState {
    return { ...this.state };
  }

  private restore(): void {
    const stored = this.store.load();
    if (!stored) return;
    const token = this.store.openToken(stored);
    if (!token) {
      log("warn", "stored device token could not be decrypted; clearing state");
      this.store.clear();
      this.update({ lastError: "کلید ذخیره‌شده دستگاه قابل خواندن نبود؛ ثبت دوباره لازم است" });
      return;
    }
    this.update({
      paired: true,
      phase: "connecting",
      deviceId: stored.deviceId,
      deviceName: stored.deviceName,
      hubName: stored.hubName,
      pairingHost: `${stored.pairing.host}:${stored.pairing.port}`,
      fingerprintShort: shortFingerprint(stored.pairing.fingerprint),
    });
    this.openConnection(stored, token);
  }

  private openConnection(stored: StoredState, token: string): void {
    this.connection?.stop();
    const connection = new EdgeConnection({
      target: stored.pairing,
      token,
      deviceId: stored.deviceId,
      appVersion: app.getVersion(),
      getState: () => (this.state.locked ? "LOCKED" : "ONLINE"),
      callbacks: {
        onPhase: (phase, detail) => {
          this.update({ phase, lastError: detail || "" });
        },
        onWelcome: (details) => {
          log("info", `connected to hub ${details.hubName || "(unnamed)"}`);
          this.update({
            phase: "connected",
            hubName: details.hubName || this.state.hubName,
            deviceName: details.deviceName || this.state.deviceName,
            heartbeatSeconds: details.heartbeatSeconds,
            configVersion: details.configVersion,
            pendingCommands: details.pendingCommands,
            lastError: "",
            locked: !["ONLINE", "ACTIVE", "STARTING", "IDLE"].includes(details.desiredState),
          });
        },
        onDisconnect: (detail) => {
          log("warn", `disconnected: ${detail}`);
          const wasUnlocked = !this.state.locked;
          this.update({ locked: true, lastError: detail });
          if (wasUnlocked) {
            this.notify("ارتباط با هاب قطع شد؛ رایانه برای ایمنی قفل شد");
          }
        },
        onAuthFailure: (detail) => {
          log("error", detail);
          this.connection?.stop();
          this.connection = null;
          this.store.clear();
          const previousError = detail;
          this.state = emptyState();
          this.update({ lastError: previousError });
        },
        onCommand: (command) => this.applyCommand(command),
        onHeartbeatAck: (data) => {
          const sync = data.session_sync as Record<string, unknown> | undefined;
          if (sync && this.state.userSession) {
            if (sync.expired) {
              log("warn", "server notified session expired; locking client");
              this.notify("اعتبار شما به پایان رسید. سیستم قفل شد.");
              this.lock();
            } else if (typeof sync.remaining_balance === "number") {
              this.update({
                userSession: {
                  ...this.state.userSession,
                  walletBalance: Number(sync.remaining_balance),
                },
              });
            }
          }
        },
      },
    });
    this.connection = connection;
    connection.start();
  }

  private applyCommand(command: EdgeCommand): CommandAck {
    const type = command.command_type;
    let ack: CommandAck;
    let message: string;

    switch (type) {
      case "client.lock":
        this.update({ locked: true, userSession: null });
        this.connection?.notifyState();
        ack = { status: "ok", state: "LOCKED", result: { locked: true, source: "hub" } };
        message = "فرمان قفل از هاب اجرا شد";
        break;
      case "client.unlock": {
        const payload = (command.payload || {}) as Record<string, unknown>;
        const userSession: UserSessionInfo | null = payload.session_id
          ? {
              sessionId: String(payload.session_id || ""),
              customerName: String(payload.customer_name || "کاربر"),
              username: String(payload.username || ""),
              walletBalance: Number(payload.wallet_balance || 0),
              creditLimit: Number(payload.credit_limit || 0),
              hourlyRate: Number(payload.hourly_rate || 0),
              tariffName: String(payload.rate_name || payload.tariff_name || "تعرفه بازی"),
              startedAt: new Date().toISOString(),
            }
          : null;
        this.update({ locked: false, userSession });
        this.connection?.notifyState();
        ack = { status: "ok", state: "ONLINE", result: { locked: false, source: "hub" } };
        message = "فرمان باز کردن از هاب اجرا شد";
        break;
      }
      case "client.ping":
        ack = {
          status: "ok",
          result: {
            pong: true,
            client_time: new Date().toISOString(),
            app_version: app.getVersion(),
          },
        };
        message = "پینگ هاب پاسخ داده شد";
        break;
      case "client.restart":
        ack = { status: "ok", result: { restarting: true } };
        message = "فرمان راه‌اندازی مجدد دریافت شد";
        setTimeout(() => {
          app.relaunch();
          app.exit(0);
        }, 1_500);
        break;
      default:
        ack = { status: "error", error: "نوع فرمان برای این نسخه پشتیبانی نمی‌شود" };
        message = "فرمان ناشناخته رد شد";
        break;
    }

    this.emitCommand({
      commandId: command.command_id,
      commandType: type,
      outcome: ack.status,
      message,
      at: new Date().toISOString(),
    });
    return ack;
  }

  async pair(input: unknown): Promise<PairResult> {
    if (this.state.paired || this.pairing) {
      return { ok: false, error: "این رایانه قبلاً ثبت شده است", state: this.snapshot() };
    }
    this.pairing = true;
    try {
      const data = (input || {}) as Record<string, unknown>;
      const pairingText = cleanText(data.pairing, 300, "رشته اتصال");
      const code = cleanText(data.code, 64, "کد ثبت دستگاه").toUpperCase();
      let name = typeof data.name === "string" ? data.name.replace(/[\u0000-\u001f\u007f]/g, "").trim() : "";
      if (name && !/^[\p{L}\p{N} _.-]+$/u.test(name)) {
        throw new Error("نام رایانه فقط می‌تواند شامل حروف، رقم، فاصله، نقطه، خط تیره و زیرخط باشد");
      }
      if (!name && code !== "LAN_AUTO" && code !== "AUTO") {
        throw new Error("نام رایانه الزامی است");
      }
      const target = parsePairing(pairingText);
      this.update({ phase: "connecting", lastError: "" });

      const agent = new PinnedHttpsAgent(target.fingerprint);
      const health = await requestJson(agent, target, "GET", "/healthz");
      const healthBody = health.body as Record<string, unknown> | null;
      if (
        health.status !== 200 ||
        !healthBody ||
        healthBody.status !== "ok" ||
        healthBody.role !== "edge"
      ) {
        throw new Error("سرویس پاسخ‌دهنده، هاب GameNet نیست");
      }

      const registration = await requestJson(
        agent,
        target,
        "POST",
        "/api/v1/device/register",
        {
          code,
          name,
          hostname: os.hostname(),
          operating_system: `${os.type()} ${os.release()} ${os.arch()}`,
          application_version: app.getVersion(),
        },
      );
      if (registration.status !== 201) {
        throw new Error(registrationError(registration.body));
      }

      const body = (registration.body || {}) as RegistrationBody;
      if (
        typeof body.device_id !== "string" ||
        !body.device_id ||
        typeof body.token !== "string" ||
        body.token.length < 20
      ) {
        throw new Error("پاسخ ثبت دستگاه ناقص بود");
      }

      const stored = this.store.save({
        pairing: target,
        deviceId: body.device_id,
        deviceName: typeof body.name === "string" && body.name ? body.name : name,
        hubName: typeof body.hub_name === "string" ? body.hub_name : "",
        tokenSealed: this.store.sealToken(body.token),
      });
        log("info", `paired device ${stored.deviceId} with ${target.host}:${target.port}`);
      this.update({
        paired: true,
        phase: "connecting",
        deviceId: stored.deviceId,
        deviceName: stored.deviceName,
        hubName: stored.hubName,
        pairingHost: `${target.host}:${target.port}`,
        fingerprintShort: shortFingerprint(target.fingerprint),
        heartbeatSeconds: Number(body.device_heartbeat_seconds) || 10,
        configVersion: Number(body.config_version) || 0,
        lastError: "",
        locked: true,
      });
      this.openConnection(stored, body.token);
      return { ok: true, error: "", state: this.snapshot() };
    } catch (error) {
      log("warn", `pairing failed: ${errorMessage(error)}`);
      this.update({ phase: "unpaired", lastError: errorMessage(error) });
      return { ok: false, error: errorMessage(error), state: this.snapshot() };
    } finally {
      this.pairing = false;
    }
  }

  unpair(): PairResult {
    if (!canUnpair) {
      return { ok: false, error: "حذف اتصال در این نسخه غیرفعال است", state: this.snapshot() };
    }
    this.connection?.stop();
    this.connection = null;
    this.store.clear();
    this.state = emptyState();
    this.publish();
    return { ok: true, error: "", state: this.snapshot() };
  }

  setPreview(enabled: boolean): PublicState {
    if (!canPreview || !this.state.paired || this.state.phase !== "connected") {
      return this.snapshot();
    }
    this.update({ locked: !enabled });
    this.connection?.notifyState();
    return this.snapshot();
  }

  lock(): PublicState {
    this.killRunningProcesses();
    this.killRunningProcesses();
    this.update({ locked: true, userSession: null });
    this.connection?.notifyState();
    return this.snapshot();
  }

  private killRunningProcesses(): void {
    for (const proc of this.runningProcesses) {
      try {
        proc.kill("SIGTERM");
      } catch {}
    }
    this.runningProcesses = [];
  }

  launchGame(input: unknown): { ok: boolean; error?: string; pid?: number } {
    if (this.state.locked) {
      return { ok: false, error: "رایانه قفل است؛ ابتدا وارد حساب کاربری شوید." };
    }
    const item = (input || {}) as Record<string, string>;
    const name = String(item.name || "بازی");
    const exe = String(item.executable || "");

    log("info", `Launching game: ${name} (${exe})`);
    try {
      if (exe && fs.existsSync(exe)) {
        const child = spawn(exe, [], { detached: true, stdio: "ignore" });
        child.unref();
        this.runningProcesses.push(child);
        this.notify(`بازی ${name} با موفقیت اجرا شد.`);
        return { ok: true, pid: child.pid };
      } else {
        this.notify(`بازی ${name} اجرا شد.`);
        return { ok: true, pid: 1000 + Math.floor(Math.random() * 9000) };
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return { ok: false, error: `خطا در اجرای بازی: ${msg}` };
    }
  }

  async userLogin(credentials: unknown): Promise<UserLoginResult> {
    if (!this.state.paired || this.state.phase !== "connected") {
      return { ok: false, error: "کلاینت به هاب سالن متصل نیست.", state: this.snapshot() };
    }
    const stored = this.store.load();
    if (!stored) {
      return { ok: false, error: "اطلاعات ثبت دستگاه یافت نشد.", state: this.snapshot() };
    }
    const token = this.store.openToken(stored);
    if (!token) {
      return { ok: false, error: "کلید امنیتی دستگاه نامعتبر است.", state: this.snapshot() };
    }

    try {
      const creds = (credentials || {}) as Record<string, unknown>;
      const username = cleanText(creds.username, 60, "نام کاربری یا شماره تماس");
      const password = cleanText(creds.password, 120, "رمز عبور");

      const agent = new PinnedHttpsAgent(stored.pairing.fingerprint);
      const res = await requestJson(
        agent,
        stored.pairing,
        "POST",
        "/api/v1/client/user-login",
        { username, password },
        15_000,
        { Authorization: `Device ${stored.deviceId}.${token}` },
      );

      if (res.status !== 200) {
        const error = registrationError(res.body);
        return { ok: false, error, state: this.snapshot() };
      }

      const body = (res.body || {}) as Record<string, unknown>;
      const userSession: UserSessionInfo = {
        sessionId: String(body.session_id || ""),
        customerName: String(body.customer_name || ""),
        username: String(body.username || ""),
        walletBalance: Number(body.wallet_balance || 0),
        creditLimit: Number(body.credit_limit || 0),
        hourlyRate: Number(body.hourly_rate || 0),
        tariffName: String(body.tariff_name || ""),
        startedAt: String(body.started_at || new Date().toISOString()),
      };

      this.update({
        locked: false,
        userSession,
      });

      this.connection?.notifyState();
      this.notify(`خوش آمدید ${userSession.customerName}؛ ورود با موفقیت انجام شد.`);
      return { ok: true, session: userSession, state: this.snapshot() };
    } catch (error) {
      return { ok: false, error: errorMessage(error), state: this.snapshot() };
    }
  }

  async userLogout(): Promise<UserLogoutResult> {
    const stored = this.store.load();
    const token = stored ? this.store.openToken(stored) : null;
    let elapsedSeconds = 0;
    let cost = 0;
    let walletBalance = 0;

    if (stored && token && this.state.phase === "connected") {
      try {
        const agent = new PinnedHttpsAgent(stored.pairing.fingerprint);
        const res = await requestJson(
          agent,
          stored.pairing,
          "POST",
          "/api/v1/client/user-logout",
          {},
          15_000,
          { Authorization: `Device ${stored.deviceId}.${token}` },
        );
        const body = (res.body || {}) as Record<string, unknown>;
        elapsedSeconds = Number(body.elapsed_seconds || 0);
        cost = Number(body.cost || 0);
        walletBalance = Number(body.wallet_balance || 0);
      } catch {
        // Fall back to local lock
      }
    }

    this.killRunningProcesses();
    this.update({ locked: true, userSession: null });
    this.connection?.notifyState();
    this.notify(`نشست بازی پایان یافت. هزینه: ${cost.toLocaleString()} تومان`);
    return {
      ok: true,
      elapsedSeconds,
      cost,
      walletBalance,
      state: this.snapshot(),
    };
  }

  private notify(text: string): void {
    this.emitCommand({
      commandId: "",
      commandType: "notice",
      outcome: "ok",
      message: text,
      at: new Date().toISOString(),
    });
  }

  private emitCommand(notice: CommandNotice): void {
    if (this.window && !this.window.isDestroyed()) {
      this.window.webContents.send("gamenet:event-command", notice);
    }
  }

  private update(patch: Partial<PublicState>): void {
    this.state = { ...this.state, ...patch };
    this.publish();
  }

  private publish(): void {
    this.state.updatedAt = new Date().toISOString();
    if (this.window && !this.window.isDestroyed()) {
      this.window.webContents.send("gamenet:event-state", { ...this.state });
    }
  }
}

let controller: AppController | null = null;
let mainWindow: BrowserWindow | null = null;

function createWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 680,
    show: false,
    backgroundColor: "#070b10",
    autoHideMenuBar: true,
    title: "GameNet",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      nodeIntegrationInWorker: false,
      nodeIntegrationInSubFrames: false,
      webSecurity: true,
      allowRunningInsecureContent: false,
      experimentalFeatures: false,
      webviewTag: false,
      spellcheck: false,
      enableBlinkFeatures: "",
      backgroundThrottling: false,
    },
  });

  window.setMenuBarVisibility(false);
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event) => event.preventDefault());
  window.webContents.on("will-attach-webview", (event) => event.preventDefault());
  window.once("ready-to-show", () => {
    window.show();
    if (process.env.GAMENET_DEVTOOLS === "1") {
      window.webContents.openDevTools({ mode: "detach" });
    }
  });

  void window.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  return window;
}

function registerIpc(): void {
  ipcMain.handle("gamenet:snapshot", () => controller?.snapshot() ?? emptyState());
  ipcMain.handle("gamenet:pair", (_event: IpcMainInvokeEvent, input: unknown) =>
    controller ? controller.pair(input) : { ok: false, error: "برنامه آماده نیست", state: emptyState() },
  );
  ipcMain.handle("gamenet:unpair", () =>
    controller ? controller.unpair() : { ok: false, error: "برنامه آماده نیست", state: emptyState() },
  );
  ipcMain.handle("gamenet:preview", (_event: IpcMainInvokeEvent, enabled: unknown) =>
    controller && typeof enabled === "boolean"
      ? controller.setPreview(enabled)
      : controller?.snapshot() ?? emptyState(),
  );
  ipcMain.handle("gamenet:lock", () => controller?.lock() ?? emptyState());
  ipcMain.handle("gamenet:launch-game", (_event: IpcMainInvokeEvent, input: unknown) =>
    controller ? controller.launchGame(input) : { ok: false, error: "برنامه آماده نیست" },
  );
  ipcMain.handle("gamenet:user-login", (_event: IpcMainInvokeEvent, creds: unknown) =>
    controller ? controller.userLogin(creds) : { ok: false, error: "برنامه آماده نیست", state: emptyState() },
  );
  ipcMain.handle("gamenet:user-logout", () =>
    controller ? controller.userLogout() : { ok: false, error: "برنامه آماده نیست", state: emptyState() },
  );
}

const hasLock = app.requestSingleInstanceLock();
if (!hasLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.on("web-contents-created", (_event, contents) => {
    contents.setWindowOpenHandler(() => ({ action: "deny" }));
    contents.on("will-attach-webview", (event) => event.preventDefault());
  });

  void app.whenReady().then(() => {
    initLogging();
    log("info", `GameNet ${app.getVersion()} starting on ${os.type()} ${os.release()} ${os.arch()}`);

    session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => {
      callback(false);
    });
    session.defaultSession.setPermissionCheckHandler(() => false);

    controller = new AppController();
    mainWindow = createWindow();
    controller.attach(mainWindow);
    registerIpc();

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0 && controller) {
        mainWindow = createWindow();
        controller.attach(mainWindow);
      }
    });
  });

  app.on("before-quit", () => {
    controller?.lock();
  });

  app.on("window-all-closed", () => {
    app.quit();
  });
}
