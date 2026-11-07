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
  | "client.restart";

export interface PairingInput {
  /** host:port#sha256-fingerprint, exactly as shown by the edge dashboard. */
  pairing: string;
  code: string;
  name: string;
}

export interface PublicState {
  phase: ConnectionPhase;
  paired: boolean;
  locked: boolean;
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

export interface GamenetApi {
  snapshot(): Promise<PublicState>;
  pair(input: PairingInput): Promise<PairResult>;
  unpair(): Promise<PairResult>;
  preview(enabled: boolean): Promise<PublicState>;
  lock(): Promise<PublicState>;
  onState(listener: (state: PublicState) => void): () => void;
  onCommand(listener: (notice: CommandNotice) => void): () => void;
}
