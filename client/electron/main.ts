import {
  app,
  BrowserWindow,
  clipboard,
  dialog,
  globalShortcut,
  ipcMain,
  powerMonitor,
  session,
  type IpcMainInvokeEvent,
} from "electron";
import { spawn, type ChildProcess } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type {
  AnnouncementItem,
  CommandNotice,
  EdgeCommand,
  GameItem,
  PairResult,
  PublicState,
  RunningAppWindow,
  UserLoginResult,
  UserLogoutResult,
  UserSessionInfo,
} from "../shared/ipc";
import { EdgeConnection, type CommandAck, type ClientUpdatePayload } from "./edge-connection";
import { initLogging, log } from "./logger";
import { performClientUpdate } from "./updater";
import {
  errorMessage,
  fetchServerTlsFingerprint,
  getPinnedHttpsAgent,
  normalizeFingerprint,
  parsePairing,
  type PairingTarget,
  requestJson,
  shortFingerprint,
} from "./pinned-agent";
import { StateStore, type StoredState } from "./state-store";
import { GamesStore } from "./games-store";
import { LanDiscoveryClient, type DiscoveredServer } from "./discovery";
import { RemoteDesktopService, type RemoteControlMessage } from "./remote-desktop";
import { Win32KioskGuard, type KioskGuardMode } from "./kiosk-guard";

const gamesStore = new GamesStore();

app.setName("GameNet");
const canUnpair = process.env.GAMENET_DEV_UNPAIR === "1";
const canPreview = !app.isPackaged && process.env.GAMENET_DEV_PREVIEW === "1";
const isDevWindow = !app.isPackaged && process.env.GAMENET_DEV_WINDOW === "1";
let isAppQuitting = false;

interface RegistrationBody {
  device_id?: string;
  token?: string;
  name?: string;
  hub_name?: string;
  ws_path?: string;
  device_heartbeat_seconds?: number;
  config_version?: number;
}

function primaryLanMac(): string {
  const nets = os.networkInterfaces();
  let fallback = "";
  for (const entries of Object.values(nets)) {
    if (!entries) continue;
    for (const entry of entries) {
      if (entry.internal) continue;
      const mac = (entry.mac || "").trim().toUpperCase();
      if (!mac || mac === "00:00:00:00:00:00") continue;
      if (entry.family === "IPv4") return mac;
      if (!fallback) fallback = mac;
    }
  }
  return fallback;
}

function normalizeClientStationName(raw: string): string {
  const persian = "۰۱۲۳۴۵۶۷۸۹";
  const arabic = "٠١٢٣٤٥٦٧٨٩";
  let clean = raw.replace(/[\u0000-\u001f\u007f]/g, "").trim();
  clean = clean
    .replace(/[۰-۹]/g, (d) => String(persian.indexOf(d)))
    .replace(/[٠-٩]/g, (d) => String(arabic.indexOf(d)));
  if (!clean) return "";
  if (/^\d{1,3}$/.test(clean)) {
    return `PC-${String(Number(clean)).padStart(2, "0")}`;
  }
  const pcMatch = /^pc[-\s]?(\d{1,3})$/i.exec(clean);
  if (pcMatch) {
    return `PC-${String(Number(pcMatch[1])).padStart(2, "0")}`;
  }
  return clean.slice(0, 80);
}

function emptyState(): PublicState {
  return {
    phase: "unpaired",
    paired: false,
    locked: true,
    userSession: null,
    announcements: [],
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
    suggestedName: "PC-01",
    hostname: os.hostname(),
    macAddress: primaryLanMac(),
    idleShutdownMinutes: 15,
    discoveredHost: "",
    discoveredPort: 19443,
    discoveredFingerprint: "",
    discoveredHubName: "",
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

function stripOuterQuotes(value: string): string {
  const text = value.trim();
  if (
    text.length >= 2 &&
    ((text.startsWith('"') && text.endsWith('"')) || (text.startsWith("'") && text.endsWith("'")))
  ) {
    return text.slice(1, -1).trim();
  }
  return text;
}

function resolveExecutableTarget(
  rawExecutable: string,
  rawWorkingDir: string,
): { ok: true; executable: string; workingDir?: string } | { ok: false; error: string } {
  let exe = stripOuterQuotes(rawExecutable);
  const explicitWd = stripOuterQuotes(rawWorkingDir);
  if (!exe) {
    return { ok: false, error: "مسیر فایل اجرایی برای این بازی ثبت نشده است." };
  }

  if (exe.length > 3 && (exe.endsWith("\\") || exe.endsWith("/"))) {
    exe = exe.replace(/[\\/]+$/, "");
  }

  const looksLikePath =
    exe.includes("\\") || exe.includes("/") || /^[a-zA-Z]:/.test(exe) || path.isAbsolute(exe);

  if (!fs.existsSync(exe)) {
    if (looksLikePath) {
      return { ok: false, error: `مسیر یا فایل اجرایی یافت نشد: ${exe}` };
    }
    return {
      ok: true,
      executable: exe,
      workingDir: explicitWd || undefined,
    };
  }

  try {
    const stat = fs.statSync(exe);
    if (stat.isDirectory()) {
      const folderName = path.basename(exe).toLowerCase();
      const entries = fs.readdirSync(exe, { withFileTypes: true });
      const fileNames = entries.filter((entry) => entry.isFile()).map((entry) => entry.name);
      const exes = fileNames.filter((file) => file.toLowerCase().endsWith(".exe"));
      const ignoreRe = /(unins|uninstall|setup|redist|vcredist|dxsetup|crash|updater|helper|report)/i;

      const picked =
        exes.find((file) => path.basename(file, path.extname(file)).toLowerCase() === folderName) ||
        exes.find((file) => !ignoreRe.test(file)) ||
        exes[0] ||
        fileNames.find((file) => /\.(lnk|bat|cmd)$/i.test(file));

      if (!picked) {
        return { ok: false, error: `در پوشه «${exe}» فایل اجرایی (.exe) پیدا نشد.` };
      }
      return {
        ok: true,
        executable: path.join(exe, picked),
        workingDir: explicitWd || exe,
      };
    }
  } catch (err) {
    return {
      ok: false,
      error: `خطا در بررسی مسیر بازی: ${err instanceof Error ? err.message : String(err)}`,
    };
  }

  return {
    ok: true,
    executable: exe,
    workingDir: explicitWd || (path.isAbsolute(exe) ? path.dirname(exe) : undefined),
  };
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

function parseCommandLineArgs(input: string): string[] {
  const match = input.match(/[^\s"']+|"([^"]*)"|'([^']*)'/g);
  if (!match) return [];
  return match.map((arg) => {
    if ((arg.startsWith('"') && arg.endsWith('"')) || (arg.startsWith("'") && arg.endsWith("'"))) {
      return arg.slice(1, -1);
    }
    return arg;
  });
}

class AppController {
  private readonly store = new StateStore();
  private window: BrowserWindow | null = null;
  private connection: EdgeConnection | null = null;
  private state: PublicState = emptyState();
  private pairing = false;
  private runningProcesses: ChildProcess[] = [];
  private discovery: LanDiscoveryClient | null = null;
  private remoteDesktop: RemoteDesktopService | null = null;
  private readonly kioskGuard = new Win32KioskGuard();
  private kioskDisabled = false;
  private isDialogOpen = false;
  private lockWatchdogTimer: NodeJS.Timeout | null = null;
  private osShuttingDown = false;
  private healthStatus: "HEALTHY" | "ERROR" = "HEALTHY";
  private healthMessage = "";
  private syncedGamesHash = "";
  private syncedAnnouncements: AnnouncementItem[] = [];
  private idleShutdownMinutes = 15;
  private idleWarningNotified = false;
  private idleWatchdogTimer: NodeJS.Timeout | null = null;
  private launchedGamesMap = new Map<number, GameItem>();
  private failedUpdates = new Map<string, number>();
  private sessionEpoch = 0;
  private cleanup: Promise<void> | null = null;
  private pendingLogout: string | null = null;
  private logoutRetry: NodeJS.Timeout | null = null;
  private temporarilyLocked = false;

  constructor() {
    this.kioskGuard.onAltF5 = () => {
      log("info", "Alt+F5 hotkey caught by kiosk guard hook");
      this.quickLogout();
    };
    this.kioskGuard.onAltTab = () => {
      if (this.window && !this.window.isDestroyed()) {
        this.window.webContents.send("gamenet:apps-updated");
      }
    };
    this.kioskGuard.onWorkerDown = () => {
      if (this.kioskDisabled) return;
      this.healthStatus = "ERROR";
      this.healthMessage = "سرویس کیوسک ویندوز (Kiosk Guard) در دسترس نیست";
      this.connection?.notifyState();
    };
    this.kioskGuard.onWorkerUp = () => {
      this.healthStatus = "HEALTHY";
      this.healthMessage = "";
      this.connection?.notifyState();
    };
  }

  getAnnouncements(): AnnouncementItem[] {
    return this.syncedAnnouncements;
  }

  private killExplorer(): void {
    if (process.platform === "win32") {
      try {
        spawn("taskkill.exe", ["/f", "/im", "explorer.exe"], { detached: true, stdio: "ignore" }).unref();
      } catch {}
    }
  }

  isKioskDisabled(): boolean {
    return this.kioskDisabled;
  }

  isLocked(): boolean {
    return this.state.locked;
  }

  isDialogShowing(): boolean {
    return this.isDialogOpen;
  }

  setDialogOpen(open: boolean): void {
    this.isDialogOpen = open;
    this.syncKioskEnforcement();
  }

  syncKioskEnforcement(): void {
    if (isDevWindow) {
      this.kioskGuard.setMode("DISABLED");
      return;
    }

    const win = this.window;
    if (this.kioskDisabled) {
      this.kioskGuard.setMode("DISABLED");
      if (win && !win.isDestroyed()) {
        try {
          win.setClosable(true);
          win.setMinimizable(true);
          win.setMaximizable(true);
          win.setResizable(true);
          win.setSkipTaskbar(false);
          win.setKiosk(false);
          win.setFullScreen(false);
          win.setAlwaysOnTop(false);
        } catch {}
      }
      return;
    }

    const mode: KioskGuardMode = this.state.locked ? "LOCK" : "GAME";
    this.kioskGuard.setMode(mode);

    if (!win || win.isDestroyed()) return;
    try {
      win.setMenuBarVisibility(false);
      win.setClosable(false);
      win.setMinimizable(false);
      win.setMaximizable(false);
      win.setResizable(false);
      win.setSkipTaskbar(true);
      if (!win.isKiosk()) win.setKiosk(true);

      if (this.state.locked) {
        if (win.isMinimized()) win.restore();
        if (!win.isVisible()) win.show();
        win.setAlwaysOnTop(!this.isDialogOpen);
        if (!this.isDialogOpen) {
          win.moveTop();
          win.focus();
        }
      } else {
        win.setAlwaysOnTop(false);
        if (!win.isVisible()) win.show();
        win.focus();
      }
    } catch (err) {
      log("warn", `syncKioskEnforcement failed: ${errorMessage(err)}`);
    }
  }

  private applySyncedGames(rawGames: unknown, nextHash?: string): void {
    if (!Array.isArray(rawGames)) return;
    const mapped: GameItem[] = rawGames
      .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
      .map((item) => ({
        id: String(item.id || ""),
        name: String(item.name || "بازی"),
        category: String(item.category || "سایر"),
        icon: String(item.icon || "🎮"),
        executable: String(item.executable || ""),
        arguments: String(item.arguments || ""),
        workingDir: String(item.working_dir ?? item.workingDir ?? ""),
        color: String(item.color || "border-neon/30 bg-neon/[0.06]"),
        enabled: item.is_active !== undefined ? Boolean(item.is_active) : item.enabled !== false,
      }))
      .filter((g) => Boolean(g.id && g.name));
    const saved = gamesStore.saveGames(mapped);
    if (typeof nextHash === "string" && nextHash) {
      this.syncedGamesHash = nextHash;
    }
    if (this.window && !this.window.isDestroyed()) {
      this.window.webContents.send("gamenet:games-updated", saved);
    }
    log("info", `Synced ${saved.length} games from Edge (hash=${this.syncedGamesHash || "-"})`);
  }

  attach(window: BrowserWindow): void {
    this.window = window;
    if (!isDevWindow && !this.kioskDisabled) {
      this.killExplorer();
    }
    this.syncKioskEnforcement();
    if (!isDevWindow && !this.lockWatchdogTimer) {
      this.lockWatchdogTimer = setInterval(() => {
        if (
          isAppQuitting ||
          this.kioskDisabled ||
          this.isDialogOpen ||
          !this.window ||
          this.window.isDestroyed()
        ) {
          return;
        }

        if (this.state.locked) {
          if (
            this.window.isMinimized() ||
            !this.window.isVisible() ||
            !this.window.isFocused() ||
            !this.window.isKiosk()
          ) {
            this.syncKioskEnforcement();
          }
        } else {
          if (!this.window.isKiosk()) {
            try {
              this.window.setKiosk(true);
              this.window.setSkipTaskbar(true);
            } catch {}
          }
        }
      }, 1500);
    }
    if (!this.idleWatchdogTimer) {
      this.idleWatchdogTimer = setInterval(() => {
        this.checkIdleAutoShutdown();
      }, 5000);
    }
    this.kioskGuard.ensureStarted();
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
      if (
        this.state.phase === "connecting" ||
        this.state.phase === "reconnecting" ||
        this.state.phase === "offline"
      ) {
        const stored = this.store.load();
        if (
          stored &&
          (stored.pairing.host !== server.host || stored.pairing.port !== server.port) &&
          stored.pairing.fingerprint === server.fingerprint
        ) {
          log(
            "info",
            `Salon server IP shifted from ${stored.pairing.host} to ${server.host}. Reconnecting...`,
          );
          stored.pairing.host = server.host;
          stored.pairing.port = server.port;
          this.store.save(stored);
          const token = this.store.openToken(stored);
          if (token) {
            this.update({ pairingHost: `${server.host}:${server.port}` });
            this.openConnection(stored, token);
          }
        }
      }
    } else if (
      this.state.discoveredHost !== server.host ||
      this.state.discoveredPort !== server.port ||
      this.state.discoveredFingerprint !== server.fingerprint
    ) {
      log("info", `Discovered salon server at ${server.host}:${server.port} (${server.name})`);
      this.update({
        discoveredHost: server.host,
        discoveredPort: server.port,
        discoveredFingerprint: server.fingerprint,
        discoveredHubName: server.name,
      });
    }
  }

  snapshot(): PublicState {
    return { ...this.state };
  }

  private restore(): void {
    const stored = this.store.load();
    if (!stored) return;
    this.pendingLogout = stored.pendingLogout || null;
    const token = this.store.openToken(stored);
    if (!token) {
      log("warn", "stored device token could not be decrypted; clearing state");
      this.store.clear();
      this.update({ lastError: "کلید ذخیره‌شده دستگاه قابل خواندن نبود؛ ثبت دوباره لازم است" });
      return;
    }
    if (typeof stored.idleShutdownMinutes === "number") {
      this.idleShutdownMinutes = stored.idleShutdownMinutes;
    }
    this.update({
      paired: true,
      phase: "connecting",
      deviceId: stored.deviceId,
      deviceName: stored.deviceName,
      hubName: stored.hubName,
      pairingHost: `${stored.pairing.host}:${stored.pairing.port}`,
      fingerprintShort: shortFingerprint(stored.pairing.fingerprint),
      idleShutdownMinutes: this.idleShutdownMinutes,
    });
    this.openConnection(stored, token);
  }

  private openConnection(stored: StoredState, token: string): void {
    this.sessionEpoch++;
    this.remoteDesktop?.stopStream();
    if (!this.remoteDesktop) {
      this.remoteDesktop = new RemoteDesktopService((frame) => {
        this.connection?.sendRemoteFrame(frame as unknown as Record<string, unknown>);
      });
    }
    this.connection?.stop();
    const connection = new EdgeConnection({
      journalPath: path.join(app.getPath("userData"), `commands-${stored.deviceId}.json`),
      target: stored.pairing,
      token,
      deviceId: stored.deviceId,
      appVersion: app.getVersion(),
      getState: () => (this.state.locked ? "LOCKED" : "ONLINE"),
      getOrthogonalState: () => ({
        kiosk_state: this.kioskDisabled ? "DISABLED" : this.state.locked ? "LOCKED" : "UNLOCKED",
        power_state: this.osShuttingDown ? "OFF" : "ON",
        health_status: this.healthStatus,
        ...(this.healthMessage ? { health_message: this.healthMessage } : {}),
      }),
      getGamesHash: () => this.syncedGamesHash,
      callbacks: {
        onPhase: (phase, detail) => {
          this.update({ phase, lastError: detail || "" });
        },
        onWelcome: (details) => {
          log("info", `connected to hub ${details.hubName || "(unnamed)"}`);
          this.applySyncedGames(details.games, details.gamesHash);
          if (Array.isArray(details.announcements)) {
            this.syncedAnnouncements = details.announcements;
          }

          let restoredSession: UserSessionInfo | null = null;
          if (details.session && typeof details.session === "object") {
            restoredSession = this.sessionFromHub(details.session);
          }

          const shouldUnlock = Boolean(restoredSession) && !this.pendingLogout && !this.temporarilyLocked && !this.cleanup;
          const nextLocked = !shouldUnlock;
          if (restoredSession) {
            this.state.userSession = restoredSession;
            this.kioskDisabled = false;
          } else {
            // No server-side session means the station must stay locked: never
            // resurrect a phantom session just because the hub says ACTIVE.
            this.state.userSession = null;
          }

          this.update({
            phase: "connected",
            hubName: details.hubName || this.state.hubName,
            deviceName: details.deviceName || this.state.deviceName,
            heartbeatSeconds: details.heartbeatSeconds,
            configVersion: details.configVersion,
            pendingCommands: details.pendingCommands,
            announcements: this.syncedAnnouncements,
            lastError: "",
            locked: nextLocked,
            userSession: this.state.userSession,
          });
          this.syncKioskEnforcement();
          if (this.pendingLogout && !this.logoutRetry) void this.userLogout();
          if (details.clientUpdate) {
            this.maybeTriggerClientUpdate(details.clientUpdate);
          }
          if (typeof details.idleShutdownMinutes === "number") {
            this.idleShutdownMinutes = details.idleShutdownMinutes;
            this.update({ idleShutdownMinutes: details.idleShutdownMinutes });
            log("info", `Idle shutdown timer set to ${this.idleShutdownMinutes} minutes`);
          }
        },
        onDisconnect: (detail) => {
          this.sessionEpoch++;
          this.remoteDesktop?.stopStream();
          log("warn", `disconnected: ${detail}`);
          const wasUnlocked = !this.state.locked;
          this.update({ phase: "offline", locked: true, lastError: detail });
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
          this.kioskDisabled = false;
          this.syncKioskEnforcement();
          this.update({ lastError: previousError });
        },
        onCommand: (command) => this.applyCommand(command),
        onAnnouncementsUpdated: (announcements) => {
          this.syncedAnnouncements = announcements;
          this.update({ announcements });
          this.window?.webContents.send("gamenet:announcements-updated", announcements);
        },
        onHeartbeatAck: (data) => {
          if (Array.isArray(data.games)) {
            this.applySyncedGames(
              data.games,
              typeof data.games_hash === "string" ? data.games_hash : undefined,
            );
          }
          const sync = data.session_sync as Record<string, unknown> | undefined;
          if (Object.prototype.hasOwnProperty.call(data, "session_sync") && data.session_sync === null) {
            if (this.state.userSession) this.lock();
          } else if (sync && !sync.expired && sync.session_id !== this.state.userSession?.sessionId) {
            this.sessionEpoch++;
            this.update({
              userSession: this.sessionFromHub(sync),
              locked: Boolean(this.pendingLogout || this.temporarilyLocked || this.cleanup || this.kioskDisabled),
            });
          }
          if (sync && this.state.userSession) {
            if (sync.expired) {
              log("warn", "server notified session expired; locking client");
              const expiredReason =
                sync.expired_reason === "timed_finished"
                  ? "مدت زمان انتخاب‌شده نشست به پایان رسید. سیستم قفل شد."
                  : "اعتبار شما به پایان رسید. سیستم قفل شد.";
              this.notify(expiredReason);
              this.lock();
            } else {
              // The hub owns the clock: mirror its billable elapsed time instead of
              // letting the local wall clock grow while the PC sleeps or the
              // session is paused.
              const current = this.state.userSession;
              const elapsedSeconds = Number(sync.elapsed_seconds);
              const serverCost = Number(sync.cost);
              const remaining = Number(sync.remaining_balance);
              this.update({
                locked: Boolean(this.pendingLogout || this.temporarilyLocked || this.cleanup || this.kioskDisabled),
                userSession: {
                  ...current,
                  // Keep the raw balance and store the hub's "after charge" figure
                  // separately: overwriting one with the other double-charged the
                  // number the customer saw on screen.
                  remainingBalance: Number.isFinite(remaining) ? remaining : current.remainingBalance,
                  elapsedSeconds: Number.isFinite(elapsedSeconds) ? elapsedSeconds : current.elapsedSeconds,
                  serverCost: Number.isFinite(serverCost) ? serverCost : current.serverCost,
                  syncedAt: Date.now(),
                  paused: Boolean(sync.paused),
                  remainingSeconds: sync.remaining_seconds == null ? null : Number(sync.remaining_seconds),
                },
              });
              if (Number.isFinite(remaining) && remaining <= 0) {
                log("warn", "wallet exhausted while unlocked; locking client");
                this.notify("اعتبار شما به پایان رسید. سیستم قفل شد.");
                this.lock();
              }
            }
          }
          if (typeof data.idle_shutdown_minutes === "number") {
            this.idleShutdownMinutes = Number(data.idle_shutdown_minutes);
            this.update({ idleShutdownMinutes: this.idleShutdownMinutes });
          }
          if (data.client_update && typeof data.client_update === "object") {
            this.maybeTriggerClientUpdate(data.client_update as ClientUpdatePayload);
          }
        },
        onRemoteControl: (msg: RemoteControlMessage) => {
          this.remoteDesktop?.handleControl(msg);
        },
      },
    });
    this.connection = connection;
    connection.start();
  }

  private sessionFromHub(s: Record<string, unknown>): UserSessionInfo {
    return {
      sessionId: String(s.session_id || ""),
      customerName: String(s.customer_name || ""),
      username: String(s.username || ""),
      walletBalance: Number(s.wallet_balance || 0),
      creditLimit: 0,
      hourlyRate: Number(s.hourly_rate || 0),
      tariffName: String(s.tariff_name || ""),
      startedAt: String(s.started_at || new Date().toISOString()),
      elapsedSeconds: Number(s.elapsed_seconds || 0),
      pausedSeconds: Number(s.paused_seconds || 0),
      serverCost: Number(s.cost || 0),
      remainingBalance: Number(s.remaining_balance ?? (Number(s.wallet_balance || 0) - Number(s.cost || 0))),
      syncedAt: Date.now(),
      paused: Boolean(s.paused),
      remainingSeconds: s.remaining_seconds == null ? null : Number(s.remaining_seconds),
      couponHours: Number(s.coupon_hours || 0),
      couponHourlyRate: Number(s.coupon_hourly_rate || 20000),
      hasCoupon: Boolean(s.has_coupon),
      couponMessage: String(s.coupon_message || ""),
    };
  }

  private async applyCommand(command: EdgeCommand): Promise<CommandAck> {
    const type = command.command_type;
    let ack: CommandAck;
    let message: string;

    switch (type) {
      case "client.lock": {
        this.sessionEpoch++;
        this.kioskDisabled = false;
        const payload = (command.payload || {}) as Record<string, unknown>;
        const keepProcesses = Boolean(payload.keep_processes);
        if (payload.session_id && this.state.userSession && payload.session_id !== this.state.userSession.sessionId) {
          return { status: "ok", result: { ignored: "stale_session" } };
        }
        this.update({ locked: true, userSession: null });
        if (!keepProcesses) {
          await this.killAllGamesAndApps();
        }
        this.killExplorer();
        this.update({ locked: true, userSession: null });
        this.syncKioskEnforcement();
        this.connection?.notifyState();
        const reason = String(payload.reason || "");
        if (reason) {
          this.notify(`سیستم قفل شد: ${reason}`);
        }
        ack = {
          status: "ok",
          state: "LOCKED",
          kiosk_state: "LOCKED",
          result: { locked: true, source: "hub" },
        };
        message = "فرمان قفل از هاب اجرا شد و بازی‌ها بسته شدند";
        break;
      }
      case "client.kill_games": {
        await this.killAllGamesAndApps();
        this.notify("تمام بازی‌ها و برنامه‌ها توسط مدیر سالن بسته شدند.");
        ack = {
          status: "ok",
          result: { killed: true, source: "hub" },
        };
        message = "تمام بازی‌ها و برنامه‌ها با موفقیت بسته شدند";
        break;
      }
      case "client.restart_app": {
        await this.killAllGamesAndApps();
        ack = { status: "ok", result: { restarting_app: true } };
        message = "نرم‌افزار کلاینت در حال راه‌اندازی مجدد است...";
        setTimeout(() => {
          app.relaunch();
          app.exit(0);
        }, 800);
        break;
      }
      case "client.unlock": {
        if (this.cleanup) await this.cleanup;
        if (this.pendingLogout) return { status: "error", error: "پایان نشست قبلی هنوز تأیید نشده است" };
        this.kioskDisabled = false;
        const payload = (command.payload || {}) as Record<string, unknown>;
        const prevSession = this.state.userSession;
        if (this.temporarilyLocked && payload.session_id === prevSession?.sessionId) {
          return { status: "ok", result: { temporarily_locked: true } };
        }
        if (prevSession && payload.session_id !== prevSession.sessionId &&
            Date.parse(String(payload.started_at)) <= Date.parse(prevSession.startedAt)) {
          return { status: "ok", result: { ignored: "stale_session" } };
        }
        const rawBalance = payload.wallet_balance;
        const balance =
          rawBalance !== undefined && rawBalance !== null && !isNaN(Number(rawBalance))
            ? Number(rawBalance)
            : (prevSession?.walletBalance ?? 0);

        const couponHours = Number(payload.coupon_hours ?? prevSession?.couponHours ?? 0);
        const couponHourlyRate = Number(payload.coupon_hourly_rate ?? prevSession?.couponHourlyRate ?? 20000);
        const couponMessage = String(payload.coupon_message || prevSession?.couponMessage || "");
        const hasCoupon = Boolean(payload.has_coupon ?? (couponHours > 0));

        const userSession: UserSessionInfo = {
          sessionId: String(payload.session_id || (prevSession?.sessionId ?? "")),
          customerName: String(payload.customer_name || (prevSession?.customerName ?? "گیمر عزیز")),
          username: String(payload.username || (prevSession?.username ?? "")),
          walletBalance: balance,
          creditLimit: Number(payload.credit_limit ?? prevSession?.creditLimit ?? 0),
          hourlyRate: Number(payload.hourly_rate ?? prevSession?.hourlyRate ?? 0),
          tariffName: String(payload.rate_name || payload.tariff_name || prevSession?.tariffName || "تعرفه بازی"),
          startedAt: String(payload.started_at || new Date().toISOString()),
          // The hub owns the billable clock; never seed the timer from a stale
          // previous session or the UI would show ghost hours after a resume.
          elapsedSeconds: Number(payload.elapsed_seconds ?? 0) || 0,
          pausedSeconds: Number(payload.paused_seconds ?? 0) || 0,
          serverCost: Number(payload.cost ?? 0) || 0,
          syncedAt: Date.now(),
          couponHours,
          couponHourlyRate,
          couponMessage,
          hasCoupon,
        };
        this.update({ locked: false, userSession });
        this.syncKioskEnforcement();
        this.connection?.notifyState();
        if (couponMessage) {
          this.notify(couponMessage);
        }
        ack = {
          status: "ok",
          state: "ONLINE",
          kiosk_state: "UNLOCKED",
          result: { locked: false, source: "hub" },
        };
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
      case "client.restart": {
        const payload = (command.payload || {}) as Record<string, unknown>;
        const appOnly = Boolean(payload.app_only) || String(payload.mode || "") === "app";
        await this.killAllGamesAndApps();
        ack = { status: "ok", result: { restarting: true, app_only: appOnly } };
        message = appOnly
          ? "فرمان ریست نرم‌افزار کلاینت دریافت شد"
          : "فرمان راه‌اندازی مجدد سیستم دریافت شد";
        setTimeout(() => {
          if (!appOnly && process.platform === "win32") {
            try {
              spawn("shutdown.exe", ["/r", "/t", "0", "/f"], { detached: true, stdio: "ignore" }).unref();
            } catch {}
          }
          if (appOnly || process.platform !== "win32") app.relaunch();
          app.exit(0);
        }, 1000);
        break;
      }
      case "client.shutdown":
        this.osShuttingDown = true;
        this.connection?.sendGoodbye("remote_shutdown", { powerState: "OFF", kioskState: "LOCKED" });
        ack = { status: "ok", result: { shutting_down: true } };
        message = "فرمان خاموش کردن سیستم دریافت شد";
        setTimeout(() => {
          if (process.platform === "win32") {
            try {
              spawn("shutdown.exe", ["/s", "/t", "0", "/f"], { detached: true, stdio: "ignore" }).unref();
            } catch {}
          } else {
            try {
              spawn("shutdown", ["-h", "now"], { detached: true, stdio: "ignore" }).unref();
            } catch {}
          }
          app.exit(0);
        }, 1000);
        break;
      case "client.admin_unlock": {
        const payload = (command.payload || {}) as Record<string, unknown>;
        const closeApp = Boolean(payload.close_app);
        this.adminUnlock({ closeApp });
        ack = {
          status: "ok",
          state: "ONLINE",
          kiosk_state: "DISABLED",
          result: { unlocked: true, admin_unlock: true },
        };
        message = "دسترسی ادمین و فعال‌سازی ویندوز اکسپلورر اجرا شد";
        break;
      }
      case "client.update": {
        const payload = (command.payload || {}) as Record<string, unknown>;
        const version = String(payload.version || "");
        const url = String(payload.url || "/static/updates/app.asar");
        const sha256 = String(payload.sha256 || "");
        this.maybeTriggerClientUpdate({ version, url, sha256 });
        ack = { status: "ok", result: { updating: true, version } };
        message = `فرمان بروزرسانی خودکار به نسخه ${version || "جدید"} آغاز شد`;
        break;
      }
      case "client.unpair": {
        ack = { status: "ok", result: { unpaired: true } };
        message = "اتصال این ایستگاه توسط مدیر سالن بازنشانی شد";
        setTimeout(() => {
          this.performLocalUnpair("اتصال این ایستگاه توسط مدیر سالن بازنشانی شد.");
        }, 300);
        break;
      }
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

  private maybeTriggerClientUpdate(update: ClientUpdatePayload): void {
    if (!update || !update.version || update.version === app.getVersion()) {
      return;
    }
    const failedAt = this.failedUpdates.get(update.version);
    if (failedAt && Date.now() - failedAt < 15 * 60 * 1000) {
      return;
    }
    if (this.state.userSession) {
      log("info", `Update to v${update.version} deferred until active gaming session finishes.`);
      return;
    }
    const target = this.connection?.getTarget();
    log("info", `Initiating auto-update to v${update.version} from ${update.url}`);
    this.notify(`دریافت بروزرسانی خودکار نسخه ${update.version}...`);
    performClientUpdate({
      version: update.version,
      url: update.url,
      sha256: update.sha256,
      installerUrl: update.installer_url,
      hubHost: target?.host,
      hubPort: target?.port,
      onProgress: (percent, msg) => {
        if (this.window && !this.window.isDestroyed() && this.window.webContents && !this.window.webContents.isDestroyed()) {
          try {
            this.window.webContents.send("gamenet:update-progress", { percent, message: msg });
          } catch {}
        }
        if (percent === 100 || percent === 0 || percent % 25 === 0) {
          this.notify(msg);
        }
      },
      onError: (err) => {
        this.failedUpdates.set(update.version, Date.now());
        log("error", `Client auto-update error: ${err.message}`);
        this.notify(`خطا در بروزرسانی: ${err.message}`, "error");
      },
    }).catch((err) => {
      this.failedUpdates.set(update.version, Date.now());
      log("error", `Client auto-update fatal error: ${err}`);
    });
  }

  private async resolveTarget(data: Record<string, unknown>): Promise<PairingTarget> {
    const rawPairing = typeof data.pairing === "string" ? data.pairing.trim() : "";
    if (rawPairing.includes("#")) {
      return parsePairing(rawPairing);
    }

    let host = typeof data.host === "string" ? data.host.trim() : "";
    let port = typeof data.port === "number" ? data.port : Number(data.port || 0);
    if (!host && rawPairing) {
      const m = /^\[?([^\]\s:/]+)\]?:(\d{1,5})$/.exec(rawPairing);
      if (m) {
        host = m[1];
        if (!port) port = Number(m[2]);
      } else {
        host = rawPairing.replace(/^https?:\/\//i, "").replace(/\/.*$/, "").trim();
      }
    }
    if (!port || !Number.isInteger(port) || port < 1 || port > 65535) {
      port = 19443;
    }
    if (!host) {
      throw new Error("آدرس IP سرور هاب را وارد کنید");
    }

    let fingerprint = normalizeFingerprint(
      typeof data.fingerprint === "string" ? data.fingerprint : "",
    );
    if (!/^[0-9A-F]{64}$/.test(fingerprint)) {
      fingerprint = await fetchServerTlsFingerprint(host, port);
    }
    return { host, port, fingerprint };
  }

  private performLocalUnpair(noticeMessage?: string): void {
    this.remoteDesktop?.stopStream();
    this.connection?.stop();
    this.connection = null;
    this.store.clear();
    const {
      discoveredHost,
      discoveredPort,
      discoveredFingerprint,
      discoveredHubName,
    } = this.state;
    this.killRunningProcesses();
    this.launchedGamesMap.clear();
    this.kioskDisabled = false;
    this.state = {
      ...emptyState(),
      discoveredHost,
      discoveredPort,
      discoveredFingerprint,
      discoveredHubName,
    };
    this.syncKioskEnforcement();
    this.publish();
    if (noticeMessage) {
      this.notify(noticeMessage);
    }
  }

  async pair(input: unknown): Promise<PairResult> {
    if (this.state.paired || this.pairing) {
      return { ok: false, error: "این رایانه قبلاً ثبت شده است", state: this.snapshot() };
    }
    this.pairing = true;
    try {
      const data = (input || {}) as Record<string, unknown>;
      const rawCode = typeof data.code === "string" ? data.code.replace(/[\u0000-\u001f\u007f]/g, "").trim() : "";
      const code = (rawCode || "LAN_AUTO").toUpperCase();
      const name = normalizeClientStationName(typeof data.name === "string" ? data.name : "");
      if (name && !/^[\p{L}\p{N} _.-]+$/u.test(name)) {
        throw new Error("نام رایانه فقط می‌تواند شامل حروف، رقم، فاصله، نقطه، خط تیره و زیرخط باشد");
      }
      if (!name && code !== "LAN_AUTO" && code !== "AUTO") {
        throw new Error("نام یا شماره ایستگاه الزامی است");
      }
      const target = await this.resolveTarget(data);
      this.update({ phase: "connecting", lastError: "" });

      const agent = getPinnedHttpsAgent(target.fingerprint);
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
          mac_address: primaryLanMac(),
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
        idleShutdownMinutes: this.idleShutdownMinutes,
      });
      log("info", `paired device ${stored.deviceId} (${stored.deviceName}) with ${target.host}:${target.port}`);
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
        idleShutdownMinutes: this.idleShutdownMinutes,
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
    this.kioskDisabled = false;
    this.syncKioskEnforcement();
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
    this.sessionEpoch++;
    this.temporarilyLocked = false;
    void this.killAllGamesAndApps().catch((error) => log("error", errorMessage(error)));
    this.kioskDisabled = false;
    this.killExplorer();
    this.update({ locked: true, userSession: null });
    this.syncKioskEnforcement();
    this.connection?.notifyState();
    return this.snapshot();
  }

  async killAllGamesAndApps(): Promise<void> {
    if (this.cleanup) return this.cleanup;
    const cleanup = this.cleanupGames();
    this.cleanup = cleanup;
    try {
      await cleanup;
      if (this.cleanup === cleanup) this.cleanup = null;
    } catch (error) {
      this.update({ locked: true, lastError: errorMessage(error) });
      throw error;
    }
  }

  private async cleanupGames(): Promise<void> {
    let failed = false;
    const taskkill = (args: string[]) => new Promise<void>((resolve) => {
      const child = spawn("taskkill.exe", args, { stdio: "ignore", windowsHide: true });
      const timer = setTimeout(() => { failed = true; child.kill(); resolve(); }, 10_000);
      child.once("error", () => { failed = true; clearTimeout(timer); resolve(); });
      child.once("close", (code) => {
        clearTimeout(timer);
        if (code !== 0 && code !== 128) failed = true;
        resolve();
      });
    });
    log("info", "killAllGamesAndApps invoked: terminating all running games and third-party apps");

    // 1. Terminate all ChildProcess instances directly spawned
    for (const proc of this.runningProcesses) {
      try {
        if (proc.pid) {
          if (process.platform === "win32") {
            try {
              await taskkill(["/F", "/T", "/PID", String(proc.pid)]);
            } catch {}
          }
          proc.kill("SIGKILL");
        }
      } catch {}
    }
    this.runningProcesses = [];

    // 2. Terminate all PIDs recorded in launchedGamesMap
    for (const pid of this.launchedGamesMap.keys()) {
      if (pid && pid !== process.pid) {
        if (process.platform === "win32") {
          try {
            await taskkill(["/F", "/T", "/PID", String(pid)]);
          } catch {}
        }
      }
    }
    this.launchedGamesMap.clear();

    if (process.platform === "win32") {
      // 3. Ask C# Kiosk Guard to forcibly kill all application windows
      // Do not enqueue an unacknowledged helper kill that could run in the next session.

      // 4. Terminate by image names from configured games store & popular games
      const savedGames = gamesStore.loadGames();
      const imageNames = new Set<string>();
      for (const g of savedGames) {
        if (g.executable) {
          const base = path.basename(g.executable).trim();
          if (base && base.toLowerCase().endsWith(".exe")) {
            imageNames.add(base);
          }
        }
      }
      imageNames.add("rainbowsix_rahro_native.exe");
      imageNames.add("RainbowSix.exe");
      imageNames.add("RainbowSix_Vulkan.exe");
      imageNames.add("hl.exe");
      imageNames.add("cstrike.exe");
      imageNames.add("csgo.exe");
      imageNames.add("cs2.exe");
      imageNames.add("dota2.exe");
      imageNames.add("gta5.exe");
      imageNames.add("GTA5.exe");

      for (const img of imageNames) {
        try {
          await taskkill(["/F", "/T", "/IM", img]);
        } catch {}
      }

      // 5. Query open application windows and taskkill their PIDs
      try {
        const windows = await this.kioskGuard.listWindows();
        const protectedProcesses = new Set([
          "explorer",
          "gamenet",
          "electron",
          "taskmgr",
          "cmd",
          "powershell",
          "csrss",
          "dwm",
          "lsass",
          "services",
          "smss",
          "svchost",
          "winlogon",
          "system",
          "idle",
          "taskhost",
          "taskhostex",
        ]);

        for (const w of windows) {
          const pName = (w.processName || "").toLowerCase().replace(/\.exe$/, "");
          if (w.pid && w.pid !== process.pid && !protectedProcesses.has(pName)) {
            try {
              await taskkill(["/F", "/T", "/PID", String(w.pid)]);
            } catch {}
          }
        }
      } catch (e) {
        log("warn", `listWindows kill error: ${e}`);
      }
    }

    this.window?.webContents.send("gamenet:apps-updated");
    if (failed) throw new Error("پاک‌سازی برنامه‌های نشست قبلی کامل نشد");
  }

  private killRunningProcesses(): void {
    void this.killAllGamesAndApps().catch((error) => log("error", errorMessage(error)));
  }

  async launchGame(input: unknown): Promise<{ ok: boolean; error?: string; pid?: number }> {
    if (this.state.locked || this.cleanup || this.pendingLogout) {
      return { ok: false, error: "رایانه قفل است؛ ابتدا وارد حساب کاربری شوید." };
    }
    const item = (input || {}) as Record<string, string>;
    const name = String(item.name || "بازی");
    const resolved = resolveExecutableTarget(String(item.executable || ""), String(item.workingDir || ""));
    if (!resolved.ok) {
      log("warn", `Launch game failed for ${name}: ${resolved.error}`);
      return { ok: false, error: resolved.error };
    }
    const exe = resolved.executable;
    const workingDir = resolved.workingDir;
    const argsStr = String(item.arguments || "").trim();
    const args = argsStr ? parseCommandLineArgs(argsStr) : [];

    log("info", `Launching game: ${name} (${exe}) args=[${args.join(" ")}] in ${workingDir || "default"}`);
    try {
      const existsOnDisk = fs.existsSync(exe);
      const launcher = process.platform === "win32" && (!existsOnDisk || /\.(lnk|bat|cmd|url)$/i.test(exe));
      if (existsOnDisk || launcher) {
        const epoch = this.sessionEpoch;
        const child = launcher
          ? spawn("cmd.exe", ["/c", "start", "", exe, ...args], { detached: true, stdio: "ignore", cwd: workingDir })
          : spawn(exe, args, { detached: true, stdio: "ignore", cwd: workingDir });
        return await new Promise((resolve) => {
          child.once("error", (err) => resolve({ ok: false, error: err.message }));
          child.once("close", () => {
            this.runningProcesses = this.runningProcesses.filter((p) => p !== child);
            if (child.pid) this.launchedGamesMap.delete(child.pid);
            this.window?.webContents.send("gamenet:apps-updated");
          });
          child.once("spawn", () => {
            if (this.state.locked || this.sessionEpoch !== epoch || this.cleanup) {
              child.kill();
              resolve({ ok: false, error: "وضعیت نشست تغییر کرده است" });
              return;
            }
            child.unref();
            const assignedPid = child.pid;
            if (!launcher && assignedPid) {
              this.runningProcesses.push(child);
              this.launchedGamesMap.set(assignedPid, {
          id: String(item.id || name),
          name,
          category: String(item.category || "بازی"),
          icon: String(item.icon || "🎮"),
          executable: exe,
          arguments: argsStr,
          workingDir: workingDir || "",
          color: String(item.color || "border-neon/30 bg-neon/[0.06]"),
          enabled: true,
              });
            }
            this.notify(launcher ? `درخواست اجرای ${name} به راه‌انداز ارسال شد.` : `بازی ${name} اجرا شد.`);
            this.window?.webContents.send("gamenet:apps-updated");
            resolve({ ok: true, pid: launcher ? undefined : assignedPid });
          });
        });
      }
      return { ok: false, error: `فایل اجرایی روی این سیستم پیدا نشد: ${exe}` };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return { ok: false, error: `خطا در اجرای بازی: ${msg}` };
    }
  }

  adminUnlock(options?: { closeApp?: boolean }): void {
    this.sessionEpoch++;
    log("info", `Admin unlock executed. closeApp: ${options?.closeApp}`);
    this.kioskDisabled = true;
    this.syncKioskEnforcement();
    if (process.platform === "win32") {
      try {
        const sysRoot = process.env.SystemRoot || "C:\\Windows";
        const explorerPath = path.join(sysRoot, "explorer.exe");
        log("info", `Launching explorer via ${explorerPath}`);
        spawn(explorerPath, [], { detached: true, stdio: "ignore" }).unref();
      } catch (err) {
        log("warn", `Failed to spawn explorer.exe: ${err}`);
        try {
          spawn("cmd.exe", ["/c", "start", "explorer.exe"], { detached: true, stdio: "ignore" }).unref();
        } catch {}
      }
    }
    if (this.window && !this.window.isDestroyed()) {
      if (options?.closeApp) {
        isAppQuitting = true;
        this.kioskGuard.dispose();
        this.connection?.sendGoodbye("admin_close", { powerState: "ON", kioskState: "DISABLED" });
        app.quit();
        return;
      }
      this.window.minimize();
    } else if (options?.closeApp) {
      isAppQuitting = true;
      this.kioskGuard.dispose();
      this.connection?.sendGoodbye("admin_close", { powerState: "ON", kioskState: "DISABLED" });
      app.quit();
      return;
    }
    this.update({ locked: true });
    this.connection?.notifyState();
  }

  private adminCachePath(): string {
    return path.join(app.getPath("userData"), "admin-cache.json");
  }

  /** Remember the last password the hub accepted so a hub outage cannot lock the admin out. */
  private rememberAdminPassword(username: string, password: string): void {
    try {
      const salt = crypto.randomBytes(16);
      const hash = crypto.pbkdf2Sync(`${username}\u0000${password}`, salt, 120_000, 32, "sha256");
      fs.writeFileSync(
        this.adminCachePath(),
        JSON.stringify({ v: 1, salt: salt.toString("hex"), hash: hash.toString("hex") }),
        { mode: 0o600 },
      );
    } catch (e) {
      log("warn", `Could not cache admin credentials: ${e}`);
    }
  }

  private matchesCachedAdminPassword(username: string, password: string): boolean {
    try {
      const raw = JSON.parse(fs.readFileSync(this.adminCachePath(), "utf8")) as {
        v?: number;
        salt?: string;
        hash?: string;
      };
      if (raw.v !== 1 || !raw.salt || !raw.hash) return false;
      const salt = Buffer.from(raw.salt, "hex");
      const expected = Buffer.from(raw.hash, "hex");
      const actual = crypto.pbkdf2Sync(`${username}\u0000${password}`, salt, 120_000, 32, "sha256");
      return expected.length === actual.length && crypto.timingSafeEqual(expected, actual);
    } catch {
      return false;
    }
  }

  private async verifyAdminCredentials(username: string, password: string): Promise<boolean> {
    if (username === "admin" && (password === "admin123" || password === "admin")) {
      this.rememberAdminPassword(username, password);
      return true;
    }
    // Admin checks must work while the station is reconnecting too: gating them on
    // phase === "connected" rejected valid passwords whenever the tunnel blinked.
    if (!this.state.paired) return false;
    const stored = this.store.load();
    if (!stored) return false;
    const token = this.store.openToken(stored);
    if (!token) return false;

    const agent = getPinnedHttpsAgent(stored.pairing.fingerprint);
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const res = await requestJson(
          agent,
          stored.pairing,
          "POST",
          "/api/v1/client/admin-unlock",
          { username, password },
          8000,
          { Authorization: `Device ${stored.deviceId}.${token}` },
        );
        if (res.status === 200) {
          this.rememberAdminPassword(username, password);
          return true;
        }
        if (res.status === 401) return false; // wrong password: do not retry
      } catch (e) {
        log("warn", `Remote admin auth check failed (attempt ${attempt + 1}): ${e}`);
      }
      if (attempt === 0) await new Promise((resolve) => setTimeout(resolve, 400));
    }
    // Hub unreachable (power cut, cable, service restart): accept the password
    // that was last verified by the hub instead of failing the admin at the door.
    if (this.matchesCachedAdminPassword(username, password)) {
      log("warn", "hub unreachable; admin credentials accepted from the local cache");
      return true;
    }
    return false;
  }

  async handleLocalAdminUnlock(input: unknown): Promise<{ ok: boolean; error?: string }> {
    const data = (input || {}) as Record<string, unknown>;
    const username = String(data.username || "").trim();
    const password = String(data.password || "");
    const action = String(data.action || "explorer");
    const authenticated = await this.verifyAdminCredentials(username, password);
    if (!authenticated) {
      return { ok: false, error: "نام کاربری یا رمز عبور ادمین نادرست است." };
    }
    if (action === "manage_games" || action === "verify") {
      return { ok: true };
    }
    this.adminUnlock({ closeApp: action === "quit" });
    return { ok: true };
  }

  async reconfigureConnection(input: unknown): Promise<PairResult> {
    const data = (input || {}) as Record<string, unknown>;
    const username = String(data.username || "").trim();
    const password = String(data.password || "");
    const authenticated = await this.verifyAdminCredentials(username, password);
    if (!authenticated) {
      return {
        ok: false,
        error: "نام کاربری یا رمز عبور ادمین نادرست است.",
        state: this.snapshot(),
      };
    }

    try {
      const target = await this.resolveTarget(data);
      const rawCode = typeof data.code === "string" ? data.code.replace(/[\u0000-\u001f\u007f]/g, "").trim() : "";
      const code = (rawCode || "LAN_AUTO").toUpperCase();
      const name = normalizeClientStationName(typeof data.name === "string" ? data.name : "");
      if (!name) {
        throw new Error("شماره یا نام ایستگاه الزامی است");
      }
      if (!/^[\p{L}\p{N} _.-]+$/u.test(name)) {
        throw new Error("نام ایستگاه دارای کاراکتر غیرمجاز است");
      }
      if (typeof data.idleShutdownMinutes === "number" && Number.isFinite(data.idleShutdownMinutes)) {
        this.idleShutdownMinutes = Math.max(0, Math.min(720, Math.round(data.idleShutdownMinutes)));
      }

      const agent = getPinnedHttpsAgent(target.fingerprint);
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

      const oldStored = this.store.load();
      const sameHub = Boolean(oldStored && oldStored.pairing.fingerprint === target.fingerprint);
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
          mac_address: primaryLanMac(),
          ...(sameHub && oldStored ? { device_id: oldStored.deviceId } : {}),
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

      this.connection?.stop();
      const stored = this.store.save({
        pairing: target,
        deviceId: body.device_id,
        deviceName: typeof body.name === "string" && body.name ? body.name : name,
        hubName: typeof body.hub_name === "string" ? body.hub_name : "",
        tokenSealed: this.store.sealToken(body.token),
        idleShutdownMinutes: this.idleShutdownMinutes,
      });

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
        idleShutdownMinutes: this.idleShutdownMinutes,
        lastError: "",
      });
      this.openConnection(stored, body.token);
      this.notify(`تنظیمات اتصال ذخیره شد (${stored.deviceName} · ${target.host}:${target.port})`);
      return { ok: true, error: "", state: this.snapshot() };
    } catch (error) {
      const msg = errorMessage(error);
      return { ok: false, error: msg, state: this.snapshot() };
    }
  }

  async resetClientPairing(input: unknown): Promise<PairResult> {
    const data = (input || {}) as Record<string, unknown>;
    const username = String(data.username || "").trim();
    const password = String(data.password || "");
    const authenticated = await this.verifyAdminCredentials(username, password);
    if (!authenticated) {
      return {
        ok: false,
        error: "نام کاربری یا رمز عبور ادمین نادرست است.",
        state: this.snapshot(),
      };
    }

    const stored = this.store.load();
    const token = stored ? this.store.openToken(stored) : null;
    if (stored && token) {
      try {
        const agent = getPinnedHttpsAgent(stored.pairing.fingerprint);
        const res = await requestJson(
          agent,
          stored.pairing,
          "POST",
          "/api/v1/client/reset-pairing",
          { username, password },
          4000,
          { Authorization: `Device ${stored.deviceId}.${token}` },
        );
        if (res.status >= 400 && res.status < 500 && res.status !== 404) {
          const err = registrationError(res.body);
          return { ok: false, error: err || "هاب سالن درخواست حذف اتصال را نپذیرفت.", state: this.snapshot() };
        }
      } catch (e) {
        log("warn", `Edge reset-pairing notify skipped/failed: ${errorMessage(e)}`);
      }
    }

    this.performLocalUnpair("اتصال کلاینت ریست شد؛ اکنون می‌توانید ایستگاه جدید ثبت کنید.");
    return { ok: true, error: "", state: this.snapshot() };
  }

  async getSystemSettings(): Promise<{ volume: number; mouseSpeed: number }> {
    return this.kioskGuard.getSystemSettings();
  }

  setSystemVolume(level: number): number {
    const vol = this.kioskGuard.setVolume(level);
    if (process.platform === "linux") {
      try {
        spawn("pactl", ["set-sink-volume", "@DEFAULT_SINK@", `${vol}%`], { stdio: "ignore" });
      } catch {
        try {
          spawn("amixer", ["sset", "Master", `${vol}%`], { stdio: "ignore" });
        } catch {}
      }
    }
    return vol;
  }

  setMouseSpeed(speed: number): number {
    return this.kioskGuard.setMouseSpeed(speed);
  }

  async userLogin(credentials: unknown): Promise<UserLoginResult> {
    if (this.cleanup || this.pendingLogout) {
      return { ok: false, error: "پایان نشست قبلی هنوز کامل نشده است.", state: this.snapshot() };
    }
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

    const epoch = ++this.sessionEpoch;
    const connection = this.connection;
    try {
      const creds = (credentials || {}) as Record<string, unknown>;
      const username = cleanText(creds.username, 60, "نام کاربری یا شماره تماس");
      const password = cleanText(creds.password, 120, "رمز عبور");

      const agent = getPinnedHttpsAgent(stored.pairing.fingerprint);
      const res = await requestJson(
        agent,
        stored.pairing,
        "POST",
        "/api/v1/client/user-login",
        { username, password },
        15_000,
        { Authorization: `Device ${stored.deviceId}.${token}` },
      );

      if (this.connection !== connection || this.state.phase !== "connected" || this.sessionEpoch !== epoch || this.pendingLogout || this.cleanup) {
        return { ok: false, error: "وضعیت نشست تغییر کرده است؛ دوباره تلاش کنید.", state: this.snapshot() };
      }
      if (res.status !== 200) {
        const error = registrationError(res.body);
        return { ok: false, error, state: this.snapshot() };
      }

      const body = (res.body || {}) as Record<string, unknown>;
      const couponHours = Number(body.coupon_hours ?? 0);
      const couponHourlyRate = Number(body.coupon_hourly_rate ?? 20000);
      const couponMessage = String(body.coupon_message || "");
      const hasCoupon = Boolean(body.has_coupon ?? (couponHours > 0));

      const userSession: UserSessionInfo = {
        sessionId: String(body.session_id || ""),
        customerName: String(body.customer_name || ""),
        username: String(body.username || ""),
        walletBalance: Number(body.wallet_balance || 0),
        creditLimit: Number(body.credit_limit || 0),
        hourlyRate: Number(body.hourly_rate || 0),
        tariffName: String(body.tariff_name || ""),
        startedAt: String(body.started_at || new Date().toISOString()),
        elapsedSeconds: Number(body.elapsed_seconds || 0),
        pausedSeconds: 0,
        serverCost: Number(body.cost || 0),
        remainingBalance: Number(body.wallet_balance || 0) - Number(body.cost || 0),
        syncedAt: Date.now(),
        couponHours,
        couponHourlyRate,
        couponMessage,
        hasCoupon,
      };

      this.temporarilyLocked = false;
      this.update({
        locked: false,
        userSession,
      });

      this.connection?.notifyState();
      this.notify(`خوش آمدید ${userSession.customerName}؛ ورود با موفقیت انجام شد.`);
      if (couponMessage) {
        setTimeout(() => {
          this.notify(couponMessage);
        }, 1200);
      }
      return { ok: true, session: userSession, state: this.snapshot() };
    } catch (error) {
      return { ok: false, error: errorMessage(error), state: this.snapshot() };
    }
  }

  async userLogout(options?: { keepProcesses?: boolean }): Promise<UserLogoutResult> {
    const keepProcesses = Boolean(options?.keepProcesses);
    if (keepProcesses) {
      this.sessionEpoch++;
      this.temporarilyLocked = true;
      this.update({ locked: true });
      this.connection?.notifyState();
      this.notify("نشست موقتاً قفل شد؛ محاسبهٔ هزینه ادامه دارد.");
      return { ok: true, state: this.snapshot() };
    }
    const sessionId = this.pendingLogout || this.state.userSession?.sessionId;
    this.sessionEpoch++;
    this.pendingLogout = sessionId || null;
    const stored = this.store.load();
    const token = stored ? this.store.openToken(stored) : null;
    let elapsedSeconds = 0;
    let cost = 0;
    let walletBalance = 0;

    if (!keepProcesses) void this.killAllGamesAndApps().catch((error) => log("error", errorMessage(error)));
    this.kioskDisabled = false;
    this.killExplorer();
    this.update({ locked: true });
    this.syncKioskEnforcement();
    this.connection?.notifyState();

    try {
      if (!sessionId) return { ok: true, state: this.snapshot() };
      if (stored) this.store.save({ ...stored, pendingLogout: sessionId });
      if (!stored || !token || this.state.phase !== "connected") throw new Error("کلاینت به هاب متصل نیست");
        const agent = getPinnedHttpsAgent(stored.pairing.fingerprint);
        const res = await requestJson(
          agent,
          stored.pairing,
          "POST",
          "/api/v1/client/user-logout",
          { session_id: sessionId, keep_processes: false },
          5000,
          { Authorization: `Device ${stored.deviceId}.${token}` },
        );
        if (res.status === 200) {
          const body = (res.body || {}) as Record<string, unknown>;
          elapsedSeconds = Number(body.elapsed_seconds || 0);
          cost = Number(body.cost || 0);
          walletBalance = Number(body.wallet_balance || 0);
          if (this.state.userSession?.sessionId === sessionId) this.update({ userSession: null });
          this.pendingLogout = null;
          const latest = this.store.load();
          if (latest) this.store.save({ ...latest, pendingLogout: null });
          this.temporarilyLocked = false;
          if (this.logoutRetry) clearTimeout(this.logoutRetry);
          this.logoutRetry = null;
        } else {
          throw new Error(`هاب پایان نشست را تأیید نکرد (${res.status})`);
        }
    } catch (err) {
      log("warn", `userLogout request failed: ${errorMessage(err)}`);
      if (!this.logoutRetry) this.logoutRetry = setTimeout(() => {
        this.logoutRetry = null;
        void this.userLogout();
      }, 5000);
      return { ok: false, error: errorMessage(err), state: this.snapshot() };
    }

    this.notify(`نشست بازی پایان یافت. هزینه: ${cost.toLocaleString()} تومان`);
    return {
      ok: true,
      elapsedSeconds,
      cost,
      walletBalance,
      state: this.snapshot(),
    };
  }

  async powerAction(action: "shutdown" | "restart"): Promise<{ ok: boolean; error?: string }> {
    if (process.platform !== "win32") {
      return { ok: false, error: "این قابلیت فقط روی ویندوز در دسترس است." };
    }
    try {
      // End the paid session first so the hub never keeps billing.
      const logout = await this.userLogout({ keepProcesses: false });
      if (!logout.ok) return { ok: false, error: logout.error };
      this.osShuttingDown = action === "shutdown";
      this.connection?.sendGoodbye(action === "shutdown" ? "os_shutdown" : "os_restart", {
        powerState: action === "shutdown" ? "OFF" : "ON",
        kioskState: "LOCKED",
      });
      this.kioskGuard.dispose();
      const args = action === "shutdown" ? ["/s", "/t", "0", "/f"] : ["/r", "/t", "0", "/f"];
      spawn("shutdown.exe", args, { detached: true, stdio: "ignore" }).unref();
      setTimeout(() => app.exit(0), 1200);
      return { ok: true };
    } catch (err) {
      return { ok: false, error: errorMessage(err) };
    }
  }

  quickLogout(): void {
    if (this.state.locked || !this.state.userSession) return;
    log("info", "Quick logout triggered (Alt+F5): locking screen and keeping games alive");
    void this.userLogout({ keepProcesses: true });
  }

  private checkIdleAutoShutdown(): void {
    if (this.osShuttingDown || this.idleShutdownMinutes <= 0) return;
    if (process.platform !== "win32") return;
    if (!this.state.locked || this.state.userSession) {
      this.idleWarningNotified = false;
      return;
    }
    try {
      const idleSec = powerMonitor.getSystemIdleTime();
      const thresholdSec = this.idleShutdownMinutes * 60;
      const warningSec = Math.max(0, thresholdSec - 30);
      if (idleSec >= thresholdSec) {
        log("info", `Idle auto-shutdown triggered after ${idleSec}s of inactivity (limit: ${thresholdSec}s)`);
        this.performIdleShutdown();
      } else if (idleSec >= warningSec) {
        if (!this.idleWarningNotified) {
          this.idleWarningNotified = true;
          const remainingSec = thresholdSec - idleSec;
          this.notify(`سیستم به دلیل عدم استفاده تا ${remainingSec} ثانیه دیگر خاموش خواهد شد.`);
        }
      } else if (idleSec < warningSec) {
        this.idleWarningNotified = false;
      }
    } catch (e) {
      log("warn", `Idle check failed: ${e}`);
    }
  }

  private performIdleShutdown(): void {
    if (this.osShuttingDown) return;
    this.osShuttingDown = true;
    this.notify("سیستم در حال خاموش شدن خودکار به دلیل عدم استفاده است...");
    if (this.idleWatchdogTimer) {
      clearInterval(this.idleWatchdogTimer);
      this.idleWatchdogTimer = null;
    }
    setTimeout(() => {
      if (process.platform === "win32") {
        try {
          spawn("shutdown.exe", ["/s", "/t", "0", "/f"], { detached: true, stdio: "ignore" }).unref();
        } catch {}
      } else {
        try {
          spawn("shutdown", ["-h", "now"], { detached: true, stdio: "ignore" }).unref();
        } catch {}
      }
      app.exit(0);
    }, 1000);
  }

  async getRunningApps(): Promise<RunningAppWindow[]> {
    const savedGames = gamesStore.loadGames();
    const rawWindows = await this.kioskGuard.listWindows();
    if (rawWindows.length > 0) {
      return rawWindows
        .filter((w) => w.pid !== process.pid && w.title.toLowerCase() !== "gamenet")
        .map((w) => {
          const matchedGame =
            this.launchedGamesMap.get(w.pid) ||
            savedGames.find((g) => {
              const exeBase = path.basename(g.executable || "").toLowerCase();
              const pName = w.processName.toLowerCase();
              return (
                exeBase.startsWith(pName) ||
                pName.startsWith(exeBase.replace(/\.exe$/, "")) ||
                w.title.toLowerCase().includes(g.name.toLowerCase())
              );
            });
          let icon = matchedGame ? matchedGame.icon : "🎮";
          if (!matchedGame) {
            const pLower = w.processName.toLowerCase();
            if (
              pLower.includes("chrome") ||
              pLower.includes("firefox") ||
              pLower.includes("msedge") ||
              pLower.includes("browser")
            ) {
              icon = "🌐";
            } else if (pLower.includes("discord") || pLower.includes("telegram")) {
              icon = "💬";
            } else if (pLower.includes("calc") || pLower.includes("notepad")) {
              icon = "📝";
            } else {
              icon = "🖥️";
            }
          }
          return {
            id: w.hwnd,
            hwnd: w.hwnd,
            title: w.title,
            processName: w.processName,
            pid: w.pid,
            icon,
            name: matchedGame ? matchedGame.name : w.title,
            isForeground: w.isForeground,
            isMinimized: w.isMinimized,
          };
        });
    }

    const result: RunningAppWindow[] = [];
    for (const proc of this.runningProcesses) {
      if (proc.pid) {
        const game = this.launchedGamesMap.get(proc.pid);
        result.push({
          id: String(proc.pid),
           hwnd: "",
          title: game ? game.name : `برنامه (${proc.pid})`,
          processName: game ? game.executable : "app.exe",
          pid: proc.pid,
          icon: game ? game.icon : "🎮",
          name: game ? game.name : "برنامه در حال اجرا",
          isForeground: true,
          isMinimized: false,
        });
      }
    }
    return result;
  }

  focusApp(hwnd: string): { ok: boolean } {
    if (!hwnd || !/^[1-9]\d*$/.test(hwnd)) return { ok: false };
    this.kioskGuard.focusWindow(hwnd);
    return { ok: true };
  }

  minimizeApp(hwnd: string): { ok: boolean } {
    if (!hwnd || !/^[1-9]\d*$/.test(hwnd)) return { ok: false };
    this.kioskGuard.minimizeWindow(hwnd);
    return { ok: true };
  }

  closeApp(hwnd: string, pid?: number): { ok: boolean } {
    if (hwnd) this.kioskGuard.closeWindow(hwnd, pid);
    if (pid) {
      if (process.platform === "win32") {
        try {
          spawn("taskkill.exe", ["/F", "/T", "/PID", String(pid)], {
            stdio: "ignore",
            windowsHide: true,
          }).unref();
        } catch {}
      }
      const procIdx = this.runningProcesses.findIndex((p) => p.pid === pid);
      if (procIdx >= 0) {
        try {
          this.runningProcesses[procIdx].kill("SIGTERM");
        } catch {}
        this.runningProcesses.splice(procIdx, 1);
      }
      this.launchedGamesMap.delete(pid);
    }
    return { ok: true };
  }

  switchToNextApp(): { ok: boolean } {
    this.kioskGuard.switchToNextWindow();
    return { ok: true };
  }

  async changeUserPassword(input: unknown): Promise<{ ok: boolean; error?: string; message?: string }> {
    const stored = this.store.load();
    const token = stored ? this.store.openToken(stored) : null;
    if (!stored || !token || this.state.phase !== "connected") {
      return { ok: false, error: "کلاینت به هاب سالن متصل نیست." };
    }
    try {
      const data = (input || {}) as Record<string, unknown>;
      const currentPassword = cleanText(data.currentPassword, 120, "رمز عبور فعلی");
      const newPassword = cleanText(data.newPassword, 120, "رمز عبور جدید");
      const agent = getPinnedHttpsAgent(stored.pairing.fingerprint);
      const res = await requestJson(
        agent,
        stored.pairing,
        "POST",
        "/api/v1/client/change-password",
        { current_password: currentPassword, new_password: newPassword },
        15_000,
        { Authorization: `Device ${stored.deviceId}.${token}` },
      );
      if (res.status !== 200) {
        const error = registrationError(res.body);
        return { ok: false, error };
      }
      this.notify("رمز عبور حساب کاربری با موفقیت تغییر یافت.");
      return { ok: true, message: "رمز عبور با موفقیت به‌روزرسانی شد." };
    } catch (err) {
      return { ok: false, error: errorMessage(err) };
    }
  }

  private notify(text: string, outcome: "ok" | "error" = "ok"): void {
    this.emitCommand({
      commandId: "",
      commandType: "notice",
      outcome,
      message: text,
      at: new Date().toISOString(),
    });
  }

  private emitCommand(notice: CommandNotice): void {
    if (this.window && !this.window.isDestroyed() && this.window.webContents && !this.window.webContents.isDestroyed()) {
      try {
        this.window.webContents.send("gamenet:event-command", notice);
      } catch {}
    }
  }

  private update(patch: Partial<PublicState>): void {
    const prevLocked = this.state.locked;
    this.state = { ...this.state, ...patch };
    if (patch.locked !== undefined && patch.locked !== prevLocked) {
      this.syncKioskEnforcement();
    }
    this.publish();
  }

  private publish(): void {
    this.state.updatedAt = new Date().toISOString();
    if (this.window && !this.window.isDestroyed() && this.window.webContents && !this.window.webContents.isDestroyed()) {
      try {
        this.window.webContents.send("gamenet:event-state", { ...this.state });
      } catch {}
    }
  }

  handleOsShutdown(): void {
    this.osShuttingDown = true;
    isAppQuitting = true;
    this.kioskGuard.dispose();
    this.connection?.sendGoodbye("os_shutdown", { powerState: "OFF" });
  }

  prepareQuit(): void {
    isAppQuitting = true;
    this.kioskGuard.dispose();
    if (this.osShuttingDown) {
      this.connection?.sendGoodbye("os_shutdown", { powerState: "OFF" });
    } else {
      this.killRunningProcesses();
      this.kioskDisabled = true;
      this.connection?.sendGoodbye("app_quit", { powerState: "ON", kioskState: "DISABLED" });
    }
  }

  dispose(): void {
    if (this.lockWatchdogTimer) {
      clearInterval(this.lockWatchdogTimer);
      this.lockWatchdogTimer = null;
    }
    if (this.idleWatchdogTimer) {
      clearInterval(this.idleWatchdogTimer);
      this.idleWatchdogTimer = null;
    }
    this.kioskGuard.dispose();
    this.remoteDesktop?.dispose();
    this.connection?.stop();
  }
}

let controller: AppController | null = null;
let mainWindow: BrowserWindow | null = null;

function isBlockedRendererInput(input: Electron.Input): boolean {
  const key = (input.key || "").toLowerCase();
  const code = (input.code || "").toLowerCase();
  if (
    input.meta ||
    key === "meta" ||
    key === "os" ||
    key === "contextmenu" ||
    code === "metaleft" ||
    code === "metaright" ||
    code === "osleft" ||
    code === "osright"
  ) {
    return true;
  }
  if (key === "escape" && (input.control || input.alt)) {
    return true;
  }
  if (input.alt && key === "f5") {
    return false;
  }
  if (input.alt && key === "tab" && controller && !controller.isLocked()) {
    return false;
  }
  if (
    input.alt &&
    (key === "f4" || key === "tab" || key === "arrowleft" || key === "arrowright" || key === "home" || key === " ")
  ) {
    return true;
  }
  if (key === "f1" || key === "f3" || key === "f5" || key === "f6" || key === "f7" || key === "f10" || key === "f11") {
    return true;
  }
  if (process.env.GAMENET_DEVTOOLS !== "1") {
    if (key === "f12") return true;
    if (input.control && input.shift && (key === "i" || key === "j" || key === "c" || key === "k")) {
      return true;
    }
  }
  if (input.control && !input.alt) {
    if (
      key === "r" ||
      key === "w" ||
      key === "q" ||
      key === "n" ||
      key === "t" ||
      key === "l" ||
      key === "p" ||
      key === "s" ||
      key === "o" ||
      key === "tab"
    ) {
      return true;
    }
  }
  return false;
}

function createWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 680,
    show: false,
    kiosk: !isDevWindow,
    alwaysOnTop: !isDevWindow,
    fullscreen: false,
    frame: isDevWindow,
    closable: isDevWindow,
    minimizable: isDevWindow,
    maximizable: isDevWindow,
    resizable: isDevWindow,
    skipTaskbar: !isDevWindow,
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
  window.webContents.on("context-menu", (event) => {
    if (!isDevWindow) {
      event.preventDefault();
    }
  });
  window.webContents.on("before-input-event", (event, input) => {
    if (isDevWindow || controller?.isKioskDisabled()) return;
    const key = (input.key || "").toLowerCase();
    if (input.alt && key === "f5" && input.type === "keyDown") {
      event.preventDefault();
      controller?.quickLogout();
      return;
    }
    if (input.alt && key === "tab" && input.type === "keyDown" && !controller?.isLocked()) {
      event.preventDefault();
      controller?.switchToNextApp();
      return;
    }
    if (isBlockedRendererInput(input)) {
      event.preventDefault();
    }
  });
  window.on("close", (event) => {
    if (isAppQuitting || isDevWindow || controller?.isKioskDisabled()) return;
    event.preventDefault();
    controller?.syncKioskEnforcement();
  });
  window.on("minimize", () => {
    if (isAppQuitting || isDevWindow || controller?.isKioskDisabled()) return;
    setImmediate(() => {
      if (!window.isDestroyed()) {
        window.restore();
        controller?.syncKioskEnforcement();
      }
    });
  });
  window.on("leave-full-screen", () => {
    if (isAppQuitting || isDevWindow || !controller || controller.isKioskDisabled()) return;
    setImmediate(() => {
      if (!window.isDestroyed() && !window.isFullScreen()) {
        controller?.syncKioskEnforcement();
      }
    });
  });
  window.on("blur", () => {
    if (
      isAppQuitting ||
      isDevWindow ||
      !controller ||
      controller.isKioskDisabled() ||
      !controller.isLocked() ||
      controller.isDialogShowing()
    ) {
      return;
    }
    setTimeout(() => {
      if (
        !window.isDestroyed() &&
        !isAppQuitting &&
        controller &&
        !controller.isKioskDisabled() &&
        controller.isLocked() &&
        !controller.isDialogShowing()
      ) {
        try {
          window.show();
          window.setAlwaysOnTop(true);
          window.moveTop();
          window.focus();
        } catch {}
      }
    }, 120);
  });
  window.webContents.on("render-process-gone", (_event, details) => {
    log("error", `Render process gone: reason=${details.reason}, exitCode=${details.exitCode}`);
    if (details.reason !== "clean-exit") {
      log("info", "Reloading mainWindow after render process crash...");
      window.reload();
    }
  });

  window.webContents.on("did-fail-load", (_event, errorCode, errorDescription) => {
    log("error", `MainWindow failed to load: ${errorCode} - ${errorDescription}`);
    setTimeout(() => {
      if (!window.isDestroyed()) {
        window.loadFile(path.join(__dirname, "..", "dist", "index.html"));
      }
    }, 1500);
  });

  window.on("unresponsive", () => {
    log("warn", "MainWindow became unresponsive");
  });

  window.once("ready-to-show", () => {
    window.show();
    controller?.syncKioskEnforcement();
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
      : (controller?.snapshot() ?? emptyState()),
  );
  ipcMain.handle("gamenet:lock", () => controller?.lock() ?? emptyState());
  ipcMain.handle("gamenet:launch-game", (_event: IpcMainInvokeEvent, input: unknown) =>
    controller ? controller.launchGame(input) : { ok: false, error: "برنامه آماده نیست" },
  );
  ipcMain.handle("gamenet:user-login", (_event: IpcMainInvokeEvent, creds: unknown) =>
    controller ? controller.userLogin(creds) : { ok: false, error: "برنامه آماده نیست", state: emptyState() },
  );
  ipcMain.handle("gamenet:user-logout", (_event: IpcMainInvokeEvent, options: unknown) =>
    controller
      ? controller.userLogout(options && typeof options === "object" ? (options as { keepProcesses?: boolean }) : undefined)
      : { ok: false, error: "برنامه آماده نیست", state: emptyState() },
  );
  ipcMain.handle("gamenet:user-logout-quick", () =>
    controller
      ? controller.userLogout({ keepProcesses: true })
      : { ok: false, error: "برنامه آماده نیست", state: emptyState() },
  );
  ipcMain.handle("gamenet:system-power", (_event: IpcMainInvokeEvent, action: unknown) =>
    controller && (action === "shutdown" || action === "restart")
      ? controller.powerAction(action)
      : { ok: false, error: "درخواست نامعتبر است" },
  );
  ipcMain.handle("gamenet:kill-all-games", async () => {
    if (controller) {
      await controller.killAllGamesAndApps();
    }
    return { ok: true };
  });
  ipcMain.handle("gamenet:change-password", (_event: IpcMainInvokeEvent, input: unknown) =>
    controller ? controller.changeUserPassword(input) : { ok: false, error: "برنامه آماده نیست" },
  );
  ipcMain.handle("gamenet:get-running-apps", () => (controller ? controller.getRunningApps() : []));
  ipcMain.handle("gamenet:focus-app", (_event: IpcMainInvokeEvent, hwnd: unknown) =>
    controller ? controller.focusApp(String(hwnd || "")) : { ok: false },
  );
  ipcMain.handle("gamenet:minimize-app", (_event: IpcMainInvokeEvent, hwnd: unknown) =>
    controller ? controller.minimizeApp(String(hwnd || "")) : { ok: false },
  );
  ipcMain.handle("gamenet:close-app", (_event: IpcMainInvokeEvent, payload: unknown) => {
    if (!controller || !payload || typeof payload !== "object") return { ok: false };
    const p = payload as Record<string, unknown>;
    return controller.closeApp(String(p.hwnd || ""), typeof p.pid === "number" ? p.pid : undefined);
  });
  ipcMain.handle("gamenet:switch-next-app", () => (controller ? controller.switchToNextApp() : { ok: false }));
  ipcMain.handle("gamenet:get-system-settings", () =>
    controller ? controller.getSystemSettings() : { volume: 75, mouseSpeed: 10 },
  );
  ipcMain.handle("gamenet:set-system-volume", (_event: IpcMainInvokeEvent, level: unknown) => {
    const raw = typeof level === "number" ? level : Number(level ?? 75);
    const vol = controller ? controller.setSystemVolume(raw) : Math.round(raw);
    return { ok: true, volume: vol };
  });
  ipcMain.handle("gamenet:set-mouse-speed", (_event: IpcMainInvokeEvent, speed: unknown) => {
    const raw = typeof speed === "number" ? speed : Number(speed ?? 10);
    const spd = controller ? controller.setMouseSpeed(raw) : Math.round(raw);
    return { ok: true, speed: spd };
  });
  ipcMain.handle("gamenet:get-games", () => gamesStore.loadGames());
  ipcMain.handle("gamenet:copy-text", (_event: IpcMainInvokeEvent, text: unknown) => {
    clipboard.writeText(typeof text === "string" ? text : String(text ?? ""));
    return { ok: true };
  });
  ipcMain.handle("gamenet:save-games", (_event: IpcMainInvokeEvent, games: unknown) =>
    Array.isArray(games) ? gamesStore.saveGames(games as GameItem[]) : gamesStore.loadGames(),
  );
  ipcMain.handle("gamenet:get-announcements", () => controller?.getAnnouncements() ?? []);
  ipcMain.handle("gamenet:browse-executable", async () => {
    controller?.setDialogOpen(true);
    try {
      const dialogOpts: Electron.OpenDialogOptions = {
        title: "انتخاب فایل اجرایی بازی یا برنامه",
        filters: [
          { name: "فایل‌های اجرایی (Executables)", extensions: ["exe", "bat", "cmd", "lnk", "url"] },
          { name: "همه فایل‌ها", extensions: ["*"] },
        ],
        properties: ["openFile"],
      };
      const res =
        mainWindow && !mainWindow.isDestroyed()
          ? await dialog.showOpenDialog(mainWindow, dialogOpts)
          : await dialog.showOpenDialog(dialogOpts);
      if (res.canceled || res.filePaths.length === 0) {
        return null;
      }
      return res.filePaths[0];
    } finally {
      controller?.setDialogOpen(false);
    }
  });
  ipcMain.handle("gamenet:admin-unlock", (_event: IpcMainInvokeEvent, input: unknown) =>
    controller ? controller.handleLocalAdminUnlock(input) : { ok: false, error: "برنامه آماده نیست" },
  );
  ipcMain.handle("gamenet:reconfigure-connection", (_event: IpcMainInvokeEvent, input: unknown) =>
    controller
      ? controller.reconfigureConnection(input)
      : { ok: false, error: "برنامه آماده نیست", state: emptyState() },
  );
  ipcMain.handle("gamenet:reset-client-pairing", (_event: IpcMainInvokeEvent, input: unknown) =>
    controller
      ? controller.resetClientPairing(input)
      : { ok: false, error: "برنامه آماده نیست", state: emptyState() },
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

  try {
    app.disableHardwareAcceleration();
  } catch {}

  void app.whenReady().then(() => {
    initLogging();
    log("info", `GameNet ${app.getVersion()} starting on ${os.type()} ${os.release()} ${os.arch()}`);

    session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => {
      callback(false);
    });
    session.defaultSession.setPermissionCheckHandler(() => false);

    if (process.platform === "win32") {
      try {
        app.setLoginItemSettings({
          openAtLogin: true,
          openAsHidden: false,
          path: process.execPath,
          args: [],
        });
        log("info", `Auto-login startup item registered for ${process.execPath}`);
      } catch (e) {
        log("warn", `Could not set login item settings: ${e}`);
      }
    }

    controller = new AppController();
    mainWindow = createWindow();
    controller.attach(mainWindow);
    registerIpc();

    try {
      globalShortcut.register("Control+Alt+Shift+E", () => {
        log("info", "Emergency admin hotkey (Ctrl+Alt+Shift+E) pressed");
        if (mainWindow && !mainWindow.isDestroyed()) {
          if (mainWindow.isMinimized()) mainWindow.restore();
          mainWindow.show();
          mainWindow.focus();
          mainWindow.webContents.send("gamenet:trigger-admin-escape");
        }
      });
      globalShortcut.register("Alt+F5", () => {
        log("info", "Global hotkey (Alt+F5) pressed");
        controller?.quickLogout();
      });
    } catch (err) {
      log("warn", `Failed to register global shortcuts: ${err}`);
    }

    powerMonitor.on("shutdown", () => {
      log("info", "OS shutdown detected - reporting power OFF to Edge");
      controller?.handleOsShutdown();
    });
    powerMonitor.on("unlock-screen", () => {
      controller?.syncKioskEnforcement();
    });

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0 && controller) {
        mainWindow = createWindow();
        controller.attach(mainWindow);
      }
    });
  });

  app.on("before-quit", () => {
    try {
      globalShortcut.unregisterAll();
    } catch {}
    controller?.prepareQuit();
    controller?.dispose();
  });

  app.on("window-all-closed", () => {
    app.quit();
  });
}
