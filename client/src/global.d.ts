import type { GamenetApi } from "../shared/ipc";

declare global {
  interface Window {
    readonly gamenet: GamenetApi;
  }
}

export {};
