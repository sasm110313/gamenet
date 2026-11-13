/**
 * The complete renderer <-> main contract. Anything not listed here cannot be
 * called from the renderer: the preload exposes this object and nothing else.
 */

export type ConnectionPhase =
  | "unpaired"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "offline";

export type CommandKind =
  | "client.lock"
  | "client.unlock"
  | "client.ping"
  | "client.restart"
  | "client.shutdown"
  | "client.admin_unlock"
  | "client.update"
  | "client.unpair"
  | "client.kill_games"
  | "client.restart_app";

export interface PairingInput {
  /** host:port#sha256-fingerprint, OR separate host/port fields below. */
  pairing?: string;
  host?: string;
  port?: number;
  fingerprint?: string;
  code: string;
  name: string;
}

export interface ReconfigureInput {
  username: string;
  password: string;
  host: string;
  port: number;
  fingerprint?: string;
  code?: string;
  name: string;
  idleShutdownMinutes?: number;
}

export interface AdminAuthInput {
  username: string;
  password: string;
}

export interface UserSessionInfo {
  sessionId: string;
  customerName: string;
  username: string;
  walletBalance: number;
  creditLimit: number;
  hourlyRate: number;
  tariffName: string;
  startedAt: string;
  /** Billable seconds reported by the hub (excludes paused/sleep time). */
  elapsedSeconds?: number;
  pausedSeconds?: number;
  paused?: boolean;
  remainingSeconds?: number | null;
  /** Cost in tomans as computed by the hub. */
  serverCost?: number;
  /** Wallet balance left after the hub charged the session (snapshot). */
  remainingBalance?: number;
  /** Local timestamp of the last hub sync, used to extrapolate between heartbeats. */
  syncedAt?: number;
  couponHours?: number;
  couponHourlyRate?: number;
  couponMessage?: string;
  hasCoupon?: boolean;
}

export interface UserLoginResult {
  ok: boolean;
  error?: string;
  session?: UserSessionInfo;
  state: PublicState;
}

export interface UserLogoutResult {
  ok: boolean;
  error?: string;
  elapsedSeconds?: number;
  cost?: number;
  walletBalance?: number;
  state: PublicState;
}

export interface LaunchGameInput {
  id: string;
  name: string;
  executable?: string;
  arguments?: string;
  workingDir?: string;
}

export interface LaunchGameResult {
  ok: boolean;
  error?: string;
  pid?: number;
}

export interface GameItem {
  id: string;
  name: string;
  category: string;
  icon: string;
  executable: string;
  arguments?: string;
  workingDir?: string;
  color?: string;
  enabled?: boolean;
}

export interface AdminUnlockInput {
  username?: string;
  password?: string;
  action?: "explorer" | "quit" | "manage_games" | "verify";
}

export interface AdminUnlockResult {
  ok: boolean;
  error?: string;
}

export interface UserChangePasswordInput {
  currentPassword: string;
  newPassword: string;
}

export interface UserChangePasswordResult {
  ok: boolean;
  error?: string;
  message?: string;
}

export interface AnnouncementItem {
  id: string;
  title: string;
  content: string;
  type?: "info" | "warning" | "success" | "danger";
  priority?: number;
  createdAt?: string;
  author?: string;
}

export interface SystemSettings {
  volume: number;
  mouseSpeed: number;
}

export interface PublicState {
  phase: ConnectionPhase;
  paired: boolean;
  locked: boolean;
  userSession?: UserSessionInfo | null;
  announcements?: AnnouncementItem[];
  deviceId: string;
  deviceName: string;
  hubName: string;
  heartbeatSeconds: number;
  configVersion: number;
  pairingHost: string;
  fingerprintShort: string;
  lastError: string;
  pendingCommands: number;
  appVersion: string;
  platform: string;
  suggestedName: string;
  hostname: string;
  macAddress: string;
  idleShutdownMinutes: number;
  discoveredHost?: string;
  discoveredPort?: number;
  discoveredFingerprint?: string;
  discoveredHubName?: string;
  canUnpair: boolean;
  canPreview: boolean;
  updatedAt: string;
}

export interface PairResult {
  ok: boolean;
  error: string;
  state: PublicState;
}

export interface CommandNotice {
  commandId: string;
  commandType: string;
  outcome: "ok" | "error";
  message: string;
  at: string;
}

export interface EdgeCommand {
  command_id: string;
  command_type: string;
  payload: Record<string, unknown>;
  expires_at: string;
}

export interface RunningAppWindow {
  id: string;
  /** Empty until a real window handle has been discovered; never a PID. */
  hwnd: string;
  title: string;
  processName: string;
  pid: number;
  icon: string;
  name: string;
  isForeground?: boolean;
  isMinimized?: boolean;
}

export interface GamenetApi {
  snapshot(): Promise<PublicState>;
  pair(input: PairingInput): Promise<PairResult>;
  unpair(): Promise<PairResult>;
  preview(enabled: boolean): Promise<PublicState>;
  lock(): Promise<PublicState>;
  launchGame(input: LaunchGameInput): Promise<LaunchGameResult>;
  userLogin(credentials: { username: string; password: string }): Promise<UserLoginResult>;
  userLogout(options?: { keepProcesses?: boolean }): Promise<UserLogoutResult>;
  userLogoutQuick(): Promise<UserLogoutResult>;
  systemPower(action: "shutdown" | "restart"): Promise<{ ok: boolean; error?: string }>;
  killAllGames(): Promise<{ ok: boolean }>;
  changeUserPassword(input: UserChangePasswordInput): Promise<UserChangePasswordResult>;
  getSystemSettings(): Promise<SystemSettings>;
  setSystemVolume(level: number): Promise<{ ok: boolean; volume: number }>;
  setMouseSpeed(speed: number): Promise<{ ok: boolean; speed: number }>;
  getGames(): Promise<GameItem[]>;
  copyText(text: string): Promise<{ ok: boolean }>;
  saveGames(games: GameItem[]): Promise<GameItem[]>;
  browseExecutable(): Promise<string | null>;
  adminUnlock(input: AdminUnlockInput): Promise<AdminUnlockResult>;
  reconfigureConnection(input: ReconfigureInput): Promise<PairResult>;
  resetClientPairing(input: AdminAuthInput): Promise<PairResult>;
  getRunningApps(): Promise<RunningAppWindow[]>;
  focusApp(hwnd: string): Promise<{ ok: boolean }>;
  minimizeApp(hwnd: string): Promise<{ ok: boolean }>;
  closeApp(hwnd: string, pid?: number): Promise<{ ok: boolean }>;
  switchNextApp(): Promise<{ ok: boolean }>;
  onState(listener: (state: PublicState) => void): () => void;
  onCommand(listener: (notice: CommandNotice) => void): () => void;
  onGamesUpdated?(listener: (games: GameItem[]) => void): () => void;
  onAnnouncementsUpdated?(listener: (announcements: AnnouncementItem[]) => void): () => void;
  onAppsUpdated?(listener: (apps: RunningAppWindow[]) => void): () => void;
  onUpdateProgress?(listener: (progress: { percent: number; message: string }) => void): () => void;
  onTriggerAdminEscape(listener: () => void): () => void;
}
