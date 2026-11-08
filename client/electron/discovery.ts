import dgram from "node:dgram";
import os from "node:os";
import { log } from "./logger";

export interface DiscoveredServer {
  service: string;
  name: string;
  host: string;
  port: number;
  fingerprint: string;
  pairing_string: string;
  auto_register: boolean;
}

export class LanDiscoveryClient {
  private socket: dgram.Socket | null = null;
  private intervalId: NodeJS.Timeout | null = null;
  private running = false;
  private onDiscovered: (server: DiscoveredServer) => void;

  constructor(onDiscovered: (server: DiscoveredServer) => void) {
    this.onDiscovered = onDiscovered;
  }

  start(port = 19445): void {
    if (this.running) return;
    this.running = true;

    try {
      this.socket = dgram.createSocket({ type: "udp4", reuseAddr: true });

      this.socket.on("error", (err) => {
        log("warn", `LAN Discovery socket error: ${err.message}`);
      });

      this.socket.on("message", (msg) => {
        try {
          const payload = JSON.parse(msg.toString("utf-8"));
          if (payload.service === "gamenet_salon_server" && payload.host && payload.fingerprint) {
            this.onDiscovered(payload as DiscoveredServer);
          }
        } catch {
          // ignore non-json
        }
      });

      this.socket.bind(0, () => {
        try {
          this.socket?.setBroadcast(true);
        } catch (e) {
          log("warn", `Failed setting UDP broadcast: ${e}`);
        }
        this.sendProbe(port);
      });

      // Poll periodically every 5 seconds
      this.intervalId = setInterval(() => {
        this.sendProbe(port);
      }, 5000);
    } catch (err) {
      log("warn", `LAN discovery client could not initialize: ${err}`);
    }
  }

  private sendProbe(port: number): void {
    if (!this.socket || !this.running) return;
    try {
      const probe = Buffer.from(
        JSON.stringify({
          query: "gamenet_discover",
          hostname: os.hostname(),
          time: Date.now(),
        })
      );
      this.socket.send(probe, 0, probe.length, port, "255.255.255.255");
    } catch (err) {
      log("debug", `Discovery probe send error: ${err}`);
    }
  }

  stop(): void {
    this.running = false;
    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
    try {
      this.socket?.close();
    } catch {
      // ignore
    }
    this.socket = null;
  }
}
