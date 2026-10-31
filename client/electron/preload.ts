import { contextBridge, ipcRenderer } from "electron";
import type {
  CommandNotice,
  GamenetApi,
  PairingInput,
  PublicState,
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
  onState: (listener: (state: PublicState) => void) =>
    subscribe<PublicState>("gamenet:event-state", listener),
  onCommand: (listener: (notice: CommandNotice) => void) =>
    subscribe<CommandNotice>("gamenet:event-command", listener),
};

contextBridge.exposeInMainWorld("gamenet", Object.freeze(api));
