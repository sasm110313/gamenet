import os from "node:os";
import fs from "node:fs";
import path from "node:path";
import WebSocket from "ws";
import type { AnnouncementItem, CommandKind, ConnectionPhase, EdgeCommand } from "../shared/ipc";
import { getPinnedHttpsAgent, type PairingTarget } from "./pinned-agent";

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

/**
 * The client side of the edge WebSocket protocol. It authenticates in the first
 * frame (never in a query string, where proxies log it), heartbeats, reconnects
 * with capped backoff, and acknowledges every command through the edge so the
 * final status reaches the cloud.
 */

const ALLOWED_COMMANDS: ReadonlySet<string> = new Set<CommandKind>([
  "client.lock",
  "client.unlock",
  "client.ping",
  "client.restart",
  "client.shutdown",
  "client.admin_unlock",
  "client.update",
  "client.unpair",
  "client.kill_games",
  "client.restart_app",
]);
const MAX_PAYLOAD_BYTES = 4 * 1024 * 1024;
const AUTH_TIMEOUT_MS = 10_000;
const COMPLETED_MEMORY = 200;

interface WelcomeMessage {
  type: "welcome";
  device_id: string;
  device_name?: string;
  hub_name?: string;
  desired_state?: string;
  heartbeat_seconds?: number;
  offline_after_missed?: number;
  config_version?: number;
  server_time?: string;
  pending_commands?: EdgeCommand[];
  games?: unknown[];
  games_hash?: string;
  announcements?: AnnouncementItem[];
  announcements_hash?: string;
  client_update?: ClientUpdatePayload;
  idle_shutdown_minutes?: number;
  session?: Record<string, unknown>;
}

export interface ClientUpdatePayload {
  version: string;
  url: string;
  sha256?: string;
  installer_url?: string;
  notes?: string;
}

export interface WelcomeDetails {
  hubName: string;
  deviceName: string;
  desiredState: string;
  heartbeatSeconds: number;
  configVersion: number;
  pendingCommands: number;
  serverTime: string;
  games?: unknown[];
  gamesHash?: string;
  announcements?: AnnouncementItem[];
  announcementsHash?: string;
  clientUpdate?: ClientUpdatePayload;
  idleShutdownMinutes?: number;
  session?: Record<string, unknown>;
}

export interface CommandAck {
  status: "ok" | "error";
  result?: Record<string, unknown>;
  error?: string;
  state?: "LOCKED" | "ONLINE";
  kiosk_state?: "LOCKED" | "UNLOCKED" | "DISABLED";
  health_status?: "HEALTHY" | "ERROR";
  health_message?: string;
}

export interface OrthogonalClientState {
  kiosk_state: "LOCKED" | "UNLOCKED" | "DISABLED";
  power_state: "ON" | "OFF";
  health_status: "HEALTHY" | "ERROR";
  health_message?: string;
}

export interface ConnectionCallbacks {
  onPhase(phase: ConnectionPhase, detail?: string): void;
  onWelcome(details: WelcomeDetails): void;
  onDisconnect(detail: string): void;
  onAuthFailure(detail: string): void;
  onCommand(command: EdgeCommand): CommandAck | Promise<CommandAck>;
  onHeartbeatAck?(data: Record<string, unknown>): void;
  onAnnouncementsUpdated?(announcements: AnnouncementItem[]): void;
  onRemoteControl?(message: Record<string, unknown>): void;
}

type AckPayload = CommandAck;

/** Raw Node TLS errors are useful in logs but not on a customer-facing screen. */
function describeError(message: string): string {
  if (/ECONNREFUSED/i.test(message)) return "هاب محلی پاسخ نمی‌دهد";
  if (/ENOTFOUND|EAI_AGAIN/i.test(message)) return "آدرس هاب پیدا نشد";
  if (/ETIMEDOUT|handshake timeout/i.test(message)) return "زمان اتصال به هاب تمام شد";
  if (/certificate|CERT_|self.signed|altnames/i.test(message)) return "گواهی TLS هاب تأیید نشد";
  return message;
}

export class EdgeConnection {
  private readonly target: PairingTarget;
  private readonly token: string;
  private readonly deviceId: string;
  private readonly appVersion: string;
  private readonly callbacks: ConnectionCallbacks;
  private readonly getState: () => "LOCKED" | "ONLINE";
  private readonly getOrthogonalState?: () => OrthogonalClientState;
  private readonly getGamesHash?: () => string;

  private socket: WebSocket | null = null;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private heartbeatTimer: NodeJS.Timeout | null = null;
  private watchdogTimer: NodeJS.Timeout | null = null;
  private authTimer: NodeJS.Timeout | null = null;
  private attempt = 0;
  private stopped = false;
  private welcomed = false;
  private lastError = "";
  private heartbeatSeconds = 10;
  /** Hub clock minus local clock: salon PCs often drift, so command TTLs must be compared in hub time. */
  private serverSkewMs = 0;
  private readonly pendingAcks = new Map<string, AckPayload>();
  private readonly completed = new Map<string, AckPayload>();
  private readonly journalPath?: string;
  private readonly journal = new Map<string, { ack: AckPayload; expiresAt: number }>();
  private readonly inFlight = new Set<string>();
  private commandQueue: Promise<void> = Promise.resolve();
  private journalUnreadable = false;

  constructor(options: {
    target: PairingTarget;
    token: string;
    deviceId: string;
    appVersion: string;
    getState: () => "LOCKED" | "ONLINE";
    getOrthogonalState?: () => OrthogonalClientState;
    getGamesHash?: () => string;
    callbacks: ConnectionCallbacks;
    journalPath?: string;
  }) {
    this.target = options.target;
    this.token = options.token;
    this.deviceId = options.deviceId;
    this.appVersion = options.appVersion;
    this.getState = options.getState;
    this.getOrthogonalState = options.getOrthogonalState;
    this.getGamesHash = options.getGamesHash;
    this.callbacks = options.callbacks;
    this.journalPath = options.journalPath;
    if (this.journalPath && fs.existsSync(this.journalPath)) {
      try {
        const records = JSON.parse(fs.readFileSync(this.journalPath, "utf8")) as [string, { ack: AckPayload; expiresAt: number }][];
        for (const [id, record] of records) {
          this.journal.set(id, record);
          this.completed.set(id, record.ack);
        }
      } catch {
        this.journalUnreadable = true;
      }
    }
  }

  private orthogonalFields(): Record<string, unknown> {
    if (!this.getOrthogonalState) return {};
    const ortho = this.getOrthogonalState();
    return {
      kiosk_state: ortho.kiosk_state,
      power_state: ortho.power_state,
      health_status: ortho.health_status,
      ...(ortho.health_message ? { health_message: ortho.health_message } : {}),
    };
  }

  /** Inform Edge before terminating about whether OS is shutting down vs app closing. */
  sendGoodbye(
    reason: string,
    options?: { powerState?: "ON" | "OFF"; kioskState?: "LOCKED" | "UNLOCKED" | "DISABLED" },
  ): void {
    if (!this.isOpen()) return;
    const ortho = this.getOrthogonalState?.();
    this.send({
      type: "goodbye",
      reason,
      power_state: options?.powerState ?? ortho?.power_state ?? "ON",
      kiosk_state: options?.kioskState ?? ortho?.kiosk_state ?? "DISABLED",
    });
  }

  start(): void {
    this.stopped = false;
    this.open();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    this.welcomed = false;
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      try {
        socket.close(1000, "client stopping");
      } catch {
        socket.terminate();
      }
    }
  }

  /** Tell the edge that the screen was locked or unlocked locally. */
  notifyState(): void {
    if (!this.isOpen()) return;
    this.send({ type: "state", state: this.getState(), ...this.orthogonalFields() });
  }

  /** Push a captured screen frame back to the edge server. */
  sendRemoteFrame(frame: Record<string, unknown>): boolean {
    if (!this.isOpen() || !this.welcomed) return false;
    return this.send({ type: "remote_frame", ...frame });
  }

  public getTarget(): PairingTarget {
    return this.target;
  }

  private open(): void {
    if (this.stopped) return;
    this.clearTimers();
    this.lastError = "";
    this.callbacks.onPhase(this.attempt === 0 ? "connecting" : "reconnecting");

    const host = this.target.host.includes(":") ? `[${this.target.host}]` : this.target.host;
    const url = `wss://${host}:${this.target.port}/ws/device/`;
    const agent = getPinnedHttpsAgent(this.target.fingerprint);
    let socket: WebSocket;

    try {
      socket = new WebSocket(url, {
        agent,
        handshakeTimeout: 12_000,
        maxPayload: MAX_PAYLOAD_BYTES,
        perMessageDeflate: false,
      });
    } catch (error) {
      this.lastError = error instanceof Error ? error.message : String(error);
      this.scheduleReconnect();
      return;
    }

    this.socket = socket;

    socket.on("open", () => {
      this.send({
        type: "hello",
        device_id: this.deviceId,
        token: this.token,
        state: this.getState(),
        app_version: this.appVersion,
        mac_address: primaryLanMac(),
        ...(this.getGamesHash ? { games_hash: this.getGamesHash() } : {}),
        ...this.orthogonalFields(),
      });
      this.authTimer = setTimeout(() => {
        if (!this.welcomed) {
          this.lastError = "هاب به احراز هویت دستگاه پاسخ نداد";
          socket.terminate();
        }
      }, AUTH_TIMEOUT_MS);
    });

    socket.on("message", (data: WebSocket.RawData, isBinary: boolean) => {
      if (this.socket !== socket || this.stopped) return;
      if (isBinary) {
        this.lastError = "هاب پیام دوتایی غیرمنتظره فرستاد";
        socket.terminate();
        return;
      }
      const text = Buffer.isBuffer(data) ? data.toString("utf8") : String(data);
      if (Buffer.byteLength(text, "utf8") > MAX_PAYLOAD_BYTES) {
        this.lastError = "پیام هاب بیش از حد بزرگ است";
        socket.terminate();
        return;
      }
      let message: Record<string, unknown>;
      try {
        const parsed = JSON.parse(text) as unknown;
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return;
        message = parsed as Record<string, unknown>;
      } catch {
        return;
      }
      this.armWatchdog();
      this.dispatch(message);
    });

    socket.on("unexpected-response", (_request, response) => {
      this.lastError = `هاب اتصال WebSocket را رد کرد (HTTP ${response.statusCode || 0})`;
      response.resume();
      socket.terminate();
    });

    socket.on("error", (error) => {
      this.lastError = describeError(error instanceof Error ? error.message : String(error));
    });

    socket.on("close", (code, reasonBuffer) => {
      if (this.socket !== socket) return;
      const reason = reasonBuffer?.toString("utf8") || "";
      this.welcomed = false;
      this.clearTimers();
      if (this.socket === socket) this.socket = null;

      if (this.stopped) return;

      if (code === 4401) {
        this.stopped = true;
        this.callbacks.onAuthFailure("اعتبار دستگاه توسط هاب رد شد؛ ثبت دوباره لازم است");
        return;
      }

      const detail =
        this.lastError ||
        (code === 1000 ? "ارتباط با هاب بسته شد" : `ارتباط با هاب قطع شد (کد ${code}${reason ? `: ${reason}` : ""})`);
      this.callbacks.onDisconnect(detail);
      this.scheduleReconnect();
    });
  }

  private dispatch(message: Record<string, unknown>): void {
    const kind = message.type;
    const serverTime = typeof message.server_time === "string" ? Date.parse(message.server_time) : NaN;
    if (Number.isFinite(serverTime)) {
      const skew = serverTime - Date.now();
      // Ignore absurd values (bad frame / broken hub clock) so we never mask real expiry.
      if (Math.abs(skew) < 24 * 3600 * 1000) this.serverSkewMs = skew;
    }
    if (kind === "welcome") {
      this.handleWelcome(message as unknown as WelcomeMessage);
      return;
    }
    if (kind === "heartbeat_ack" || kind === "games_updated") {
      this.callbacks.onHeartbeatAck?.(message);
      if (kind === "heartbeat_ack") {
        this.processCommands(message.pending_commands);
      }
      return;
    }
    if (kind === "command") {
      const command = message.command as unknown;
      if (command && typeof command === "object") {
        this.deliver(command as EdgeCommand);
      }
      return;
    }
    if (kind === "announcements_updated") {
      const list = Array.isArray(message.announcements) ? (message.announcements as AnnouncementItem[]) : [];
      this.callbacks.onAnnouncementsUpdated?.(list);
      return;
    }
    if (kind === "remote_control") {
      this.callbacks.onRemoteControl?.(message);
      return;
    }
    // pong / state_ack are liveness only; unknown types are ignored so a newer
    // edge can add fields without breaking old clients.
  }

  private handleWelcome(message: WelcomeMessage): void {
    if (String(message.device_id) !== this.deviceId) {
      this.lastError = "هاب دستگاه دیگری را تأیید کرد";
      this.socket?.terminate();
      return;
    }
    this.welcomed = true;
    if (this.authTimer) clearTimeout(this.authTimer);
    this.authTimer = null;
    this.attempt = 0;

    const heartbeatSeconds = Math.min(
      120,
      Math.max(3, Number(message.heartbeat_seconds) || 10),
    );
    this.heartbeatSeconds = heartbeatSeconds;

    this.callbacks.onWelcome({
      hubName: String(message.hub_name || ""),
      deviceName: String(message.device_name || ""),
      desiredState: String(message.desired_state || "LOCKED"),
      heartbeatSeconds,
      configVersion: Number(message.config_version) || 0,
      pendingCommands: Array.isArray(message.pending_commands)
        ? message.pending_commands.length
        : 0,
      serverTime: String(message.server_time || ""),
      games: Array.isArray(message.games) ? message.games : undefined,
      gamesHash: typeof message.games_hash === "string" ? message.games_hash : undefined,
      announcements: Array.isArray(message.announcements) ? (message.announcements as AnnouncementItem[]) : undefined,
      announcementsHash: typeof message.announcements_hash === "string" ? message.announcements_hash : undefined,
      clientUpdate: message.client_update,
      idleShutdownMinutes: typeof message.idle_shutdown_minutes === "number" ? message.idle_shutdown_minutes : undefined,
      session: message.session,
    });

    this.processCommands(message.pending_commands);
    this.startHeartbeat();
    this.flushAcks();
  }

  private startHeartbeat(): void {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = setInterval(() => {
      this.send({
        type: "heartbeat",
        state: this.getState(),
        app_version: this.appVersion,
        mac_address: primaryLanMac(),
        ...(this.getGamesHash ? { games_hash: this.getGamesHash() } : {}),
        ...this.orthogonalFields(),
      });
    }, this.heartbeatSeconds * 1000);
    this.armWatchdog();
  }

  private armWatchdog(): void {
    if (this.watchdogTimer) clearTimeout(this.watchdogTimer);
    this.watchdogTimer = setTimeout(() => {
      this.lastError = "پاسخ هاب در زمان مقرر نرسید";
      this.socket?.terminate();
    }, Math.max(30_000, this.heartbeatSeconds * 3000));
  }

  private processCommands(commands: unknown): void {
    if (!Array.isArray(commands)) return;
    for (const raw of commands.slice(0, 50)) {
      if (raw && typeof raw === "object") this.deliver(raw as EdgeCommand);
    }
  }

  private deliver(command: EdgeCommand): void {
    const id = command.command_id;
    if (this.inFlight.has(id)) return;
    this.inFlight.add(id);
    this.commandQueue = this.commandQueue.then(() => this.executeCommand(command)).catch(() => {
      this.queueAck(id, { status: "error", error: "ثبت پایدار فرمان ناموفق بود" });
    }).finally(() => this.inFlight.delete(id));
  }

  private persistCommand(id: string, ack: AckPayload, expiresAt: number): void {
    if (!this.journalPath) return;
    this.journal.set(id, { ack, expiresAt });
    const hubNow = Date.now() + this.serverSkewMs;
    for (const [key, record] of this.journal) {
      if (record.expiresAt + 2000 < hubNow) this.journal.delete(key);
    }
    fs.mkdirSync(path.dirname(this.journalPath), { recursive: true });
    const temp = `${this.journalPath}.tmp`;
    fs.writeFileSync(temp, JSON.stringify([...this.journal]), { mode: 0o600, flag: "w" });
    const fd = fs.openSync(temp, "r");
    try { fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    fs.renameSync(temp, this.journalPath);
  }

  private async executeCommand(command: EdgeCommand): Promise<void> {
    const commandId = typeof command.command_id === "string" ? command.command_id : "";
    const commandType = typeof command.command_type === "string" ? command.command_type : "";
    if (!commandId || commandId.length > 64 || !commandType) return;
    if (this.journalUnreadable) {
      this.queueAck(commandId, { status: "error", error: "سابقهٔ پایدار فرمان‌ها قابل خواندن نیست؛ بررسی مدیر لازم است" });
      return;
    }

    // Redelivery after a lost ack: never apply twice, but always re-ack.
    const already = this.completed.get(commandId);
    if (already) {
      this.queueAck(commandId, already);
      return;
    }

    let ack: AckPayload;
    if (!ALLOWED_COMMANDS.has(commandType)) {
      ack = { status: "error", error: "نوع فرمان برای این نسخه پشتیبانی نمی‌شود" };
    } else {
      const expiresAt = Date.parse(String(command.expires_at || ""));
      // Translate the hub deadline into local time before comparing, otherwise a
      // PC whose clock is a few minutes fast silently drops every command.
      const localDeadline = expiresAt - this.serverSkewMs;
      if (!Number.isFinite(expiresAt)) {
        ack = { status: "error", error: "زمان انقضای فرمان نامعتبر است" };
      } else if (localDeadline + 2000 < Date.now()) {
        ack = { status: "error", error: "فرمان پیش از رسیدن منقضی شده بود" };
      } else {
        try {
          if (["client.restart_app", "client.restart", "client.shutdown", "client.unpair"].includes(commandType)) {
            this.persistCommand(commandId, { status: "ok", result: { accepted: true } }, expiresAt);
          }
          ack = await this.callbacks.onCommand({
            ...command,
            payload:
              command.payload && typeof command.payload === "object" && !Array.isArray(command.payload)
                ? command.payload
                : {},
          });
        } catch (error) {
          ack = {
            status: "error",
            error: error instanceof Error ? error.message : String(error),
          };
        }
      }
    }

    this.completed.set(commandId, ack);
    this.persistCommand(commandId, ack, Date.parse(command.expires_at));
    if (this.completed.size > COMPLETED_MEMORY) {
      const oldest = this.completed.keys().next().value;
      if (oldest) this.completed.delete(oldest);
    }
    this.queueAck(commandId, ack);
  }

  private queueAck(commandId: string, ack: AckPayload): void {
    this.pendingAcks.set(commandId, ack);
    this.flushAcks();
  }

  private flushAcks(): void {
    if (!this.isOpen() || !this.welcomed) return;
    for (const [commandId, ack] of this.pendingAcks) {
      const sent = this.send({
        type: "command_ack",
        command_id: commandId,
        status: ack.status,
        result: ack.result,
        error: ack.error || "",
        state: ack.state,
        ...(ack.kiosk_state ? { kiosk_state: ack.kiosk_state } : {}),
        ...(ack.health_status ? { health_status: ack.health_status } : {}),
        ...(ack.health_message ? { health_message: ack.health_message } : {}),
      });
      if (!sent) return; // keep the rest queued for the next connection
      this.pendingAcks.delete(commandId);
    }
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    this.attempt += 1;
    const base = Math.min(30_000, 1000 * 2 ** Math.min(this.attempt - 1, 5));
    const delay = Math.round(base * (0.8 + Math.random() * 0.4));
    this.callbacks.onPhase(
      "reconnecting",
      `${this.lastError || "ارتباط برقرار نشد"} — تلاش دوباره در ${Math.ceil(delay / 1000)} ثانیه`,
    );
    this.reconnectTimer = setTimeout(() => this.open(), delay);
  }

  private isOpen(): boolean {
    return this.socket !== null && this.socket.readyState === WebSocket.OPEN;
  }

  private send(message: Record<string, unknown>): boolean {
    if (!this.isOpen()) return false;
    try {
      this.socket?.send(JSON.stringify(message));
      return true;
    } catch {
      return false;
    }
  }

  private clearTimers(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    if (this.watchdogTimer) clearTimeout(this.watchdogTimer);
    if (this.authTimer) clearTimeout(this.authTimer);
    this.reconnectTimer = null;
    this.heartbeatTimer = null;
    this.watchdogTimer = null;
    this.authTimer = null;
  }
}
