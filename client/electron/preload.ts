import { contextBridge, ipcRenderer } from "electron";
import type {
  AdminAuthInput,
  AdminUnlockInput,
  AdminUnlockResult,
  AnnouncementItem,
  CommandNotice,
  GameItem,
  GamenetApi,
  LaunchGameInput,
  PairingInput,
  PublicState,
  ReconfigureInput,
} from "../shared/ipc";

/**
 * The only bridge between the sandboxed renderer and the privileged main
 * process. There is no generic invoke/send, no shell, no filesystem, and no
 * ipcRenderer object exposed to page code.
 */

function subscribe<T>(channel: string, listener: (payload: T) => void): () => void {
  const wrapped = (_event: Electron.IpcRendererEvent, payload: T): void => listener(payload);
  ipcRenderer.on(channel, wrapped);
  return () => {
    ipcRenderer.removeListener(channel, wrapped);
  };
}

const api: GamenetApi = {
  snapshot: () => ipcRenderer.invoke("gamenet:snapshot") as Promise<PublicState>,
  pair: (input: PairingInput) => ipcRenderer.invoke("gamenet:pair", input),
  unpair: () => ipcRenderer.invoke("gamenet:unpair"),
  preview: (enabled: boolean) => ipcRenderer.invoke("gamenet:preview", enabled) as Promise<PublicState>,
  lock: () => ipcRenderer.invoke("gamenet:lock") as Promise<PublicState>,
  launchGame: (input: LaunchGameInput) =>
    ipcRenderer.invoke("gamenet:launch-game", input),
  userLogin: (credentials: { username: string; password: string }) =>
    ipcRenderer.invoke("gamenet:user-login", credentials),
  userLogout: (options?: { keepProcesses?: boolean }) =>
    ipcRenderer.invoke("gamenet:user-logout", options),
  userLogoutQuick: () =>
    ipcRenderer.invoke("gamenet:user-logout-quick"),
  systemPower: (action: "shutdown" | "restart") =>
    ipcRenderer.invoke("gamenet:system-power", action) as Promise<{ ok: boolean; error?: string }>,
  killAllGames: () =>
    ipcRenderer.invoke("gamenet:kill-all-games") as Promise<{ ok: boolean }>,
  changeUserPassword: (input) =>
    ipcRenderer.invoke("gamenet:change-password", input),
  getSystemSettings: () =>
    ipcRenderer.invoke("gamenet:get-system-settings"),
  setSystemVolume: (level: number) =>
    ipcRenderer.invoke("gamenet:set-system-volume", level),
  setMouseSpeed: (speed: number) =>
    ipcRenderer.invoke("gamenet:set-mouse-speed", speed),
  getGames: () =>
    ipcRenderer.invoke("gamenet:get-games") as Promise<GameItem[]>,
  copyText: (text: string) =>
    ipcRenderer.invoke("gamenet:copy-text", text) as Promise<{ ok: boolean }>,
  saveGames: (games: GameItem[]) =>
    ipcRenderer.invoke("gamenet:save-games", games) as Promise<GameItem[]>,
  browseExecutable: () =>
    ipcRenderer.invoke("gamenet:browse-executable") as Promise<string | null>,
  adminUnlock: (input: AdminUnlockInput) =>
    ipcRenderer.invoke("gamenet:admin-unlock", input) as Promise<AdminUnlockResult>,
  reconfigureConnection: (input: ReconfigureInput) =>
    ipcRenderer.invoke("gamenet:reconfigure-connection", input),
  resetClientPairing: (input: AdminAuthInput) =>
    ipcRenderer.invoke("gamenet:reset-client-pairing", input),
  getRunningApps: () =>
    ipcRenderer.invoke("gamenet:get-running-apps"),
  focusApp: (hwnd: string) =>
    ipcRenderer.invoke("gamenet:focus-app", hwnd),
  minimizeApp: (hwnd: string) =>
    ipcRenderer.invoke("gamenet:minimize-app", hwnd),
  closeApp: (hwnd: string, pid?: number) =>
    ipcRenderer.invoke("gamenet:close-app", { hwnd, pid }),
  switchNextApp: () =>
    ipcRenderer.invoke("gamenet:switch-next-app"),
  onState: (listener: (state: PublicState) => void) =>
    subscribe<PublicState>("gamenet:event-state", listener),
  onCommand: (listener: (notice: CommandNotice) => void) =>
    subscribe<CommandNotice>("gamenet:event-command", listener),
  onGamesUpdated: (listener: (games: GameItem[]) => void) =>
    subscribe<GameItem[]>("gamenet:games-updated", listener),
  onAnnouncementsUpdated: (listener: (announcements: AnnouncementItem[]) => void) =>
    subscribe<AnnouncementItem[]>("gamenet:announcements-updated", listener),
  onAppsUpdated: (listener: (apps: any) => void) =>
    subscribe<any>("gamenet:apps-updated", listener),
  onUpdateProgress: (listener: (progress: { percent: number; message: string }) => void) =>
    subscribe<{ percent: number; message: string }>("gamenet:update-progress", listener),
  onTriggerAdminEscape: (listener: () => void) =>
    subscribe<void>("gamenet:trigger-admin-escape", listener),
};

contextBridge.exposeInMainWorld("gamenet", Object.freeze(api));
