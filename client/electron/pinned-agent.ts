import https from "node:https";
import tls from "node:tls";
import type { AgentOptions } from "node:https";

/**
 * Every edge connection goes through this agent. The edge uses a self-signed
 * certificate, so chain validation is replaced by a SHA-256 pin that the
 * technician reads off the edge dashboard and enters once at pairing time.
 *
 * The agent delays handing the socket to Node's HTTP client until the TLS
 * handshake has completed and the peer certificate fingerprint matches. That
 * ordering matters: the device token is only written after the pin check, so a
 * man-in-the-middle on the LAN never receives it.
 */

export interface PairingTarget {
  host: string;
  port: number;
  fingerprint: string;
}

export class CertificatePinError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CertificatePinError";
  }
}

export function normalizeFingerprint(value: string): string {
  return String(value || "")
    .replace(/[^0-9a-fA-F]/g, "")
    .toUpperCase();
}

export function shortFingerprint(fingerprint: string): string {
  const normalized = normalizeFingerprint(fingerprint);
  if (normalized.length <= 16) return normalized;
  return `${normalized.slice(0, 8)}…${normalized.slice(-8)}`;
}

export function parsePairing(input: string): PairingTarget {
  if (typeof input !== "string") {
    throw new Error("رشته اتصال نامعتبر است");
  }
  const trimmed = input.trim();
  const hash = trimmed.lastIndexOf("#");
  if (hash <= 0 || hash === trimmed.length - 1) {
    throw new Error("رشته اتصال باید به شکل host:port#fingerprint باشد");
  }
  const endpoint = trimmed.slice(0, hash).trim();
  const fingerprint = normalizeFingerprint(trimmed.slice(hash + 1));
  if (!/^[0-9A-F]{64}$/.test(fingerprint)) {
    throw new Error("اثر انگشت گواهی هاب باید ۶۴ رقم هگزادسیمال باشد");
  }

  const bracketed = /^\[([0-9a-fA-F:]+)\]:(\d{1,5})$/.exec(endpoint);
  const plain = /^([^:\s/]+):(\d{1,5})$/.exec(endpoint);
  const match = bracketed || plain;
  if (!match) {
    throw new Error("آدرس هاب باید به شکل host:port باشد");
  }
  const host = match[1];
  const port = Number(match[2]);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("شماره پورت هاب معتبر نیست");
  }
  return { host, port, fingerprint };
}

export class PinnedHttpsAgent extends https.Agent {
  private readonly expected: string;

  constructor(fingerprint: string, options: AgentOptions = {}) {
    super({
      keepAlive: true,
      maxSockets: 4,
      ...options,
      // Identity is the fingerprint, not the public CA chain. The pin check
      // below is mandatory and runs before this socket is released to HTTP.
      rejectUnauthorized: false,
    });
    this.expected = normalizeFingerprint(fingerprint);
    if (!/^[0-9A-F]{64}$/.test(this.expected)) {
      throw new CertificatePinError("اثر انگشت گواهی معتبر نیست");
    }
  }

  // Node's agent supports the callback form; returning undefined is deliberate
  // so the socket is not used before the certificate is verified.
  createConnection(
    options: tls.ConnectionOptions,
    callback?: (err: Error | null, stream?: tls.TLSSocket) => void,
  ): tls.TLSSocket {
    const socket = tls.connect({ ...options, rejectUnauthorized: false });
    let settled = false;

    const settle = (error: Error | null): void => {
      if (settled) return;
      settled = true;
      if (error) {
        socket.destroy();
        if (callback) callback(error);
        return;
      }
      if (callback) callback(null, socket);
    };

    socket.once("secureConnect", () => {
      const certificate = socket.getPeerCertificate();
      const actual = normalizeFingerprint(certificate?.fingerprint256 || "");
      if (!actual || actual !== this.expected) {
        settle(
          new CertificatePinError(
            `گواهی هاب با اثر انگشت ثبت‌شده مطابقت ندارد (دریافت‌شده: ${
              actual ? shortFingerprint(actual) : "بدون گواهی"
            })`,
          ),
        );
        return;
      }
      settle(null);
    });

    socket.once("error", (error) => {
      settle(error instanceof Error ? error : new Error(String(error)));
    });
    socket.once("close", () => {
      if (!settled) settle(new Error("اتصال TLS پیش از تأیید گواهی بسته شد"));
    });

    return undefined as unknown as tls.TLSSocket;
  }
}

export interface JsonResponse {
  status: number;
  body: unknown;
}

export function requestJson(
  agent: PinnedHttpsAgent,
  target: PairingTarget,
  method: "GET" | "POST",
  path: string,
  body?: unknown,
  timeoutMs = 15_000,
): Promise<JsonResponse> {
  return new Promise<JsonResponse>((resolve, reject) => {
    const payload =
      body === undefined ? null : Buffer.from(JSON.stringify(body), "utf8");

    const request = https.request(
      {
        host: target.host,
        port: target.port,
        path,
        method,
        agent,
        timeout: timeoutMs,
        headers: {
          Accept: "application/json",
          "Cache-Control": "no-store",
          "User-Agent": "GameNetClient/0.1.0",
          ...(payload
            ? {
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": String(payload.byteLength),
              }
            : {}),
        },
      },
      (response) => {
        const chunks: Buffer[] = [];
        let size = 0;
        response.on("data", (chunk: Buffer) => {
          size += chunk.byteLength;
          if (size > 1_000_000) {
            request.destroy(new Error("پاسخ هاب بیش از حد بزرگ است"));
            return;
          }
          chunks.push(chunk);
        });
        response.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          if (!text) {
            resolve({ status: response.statusCode || 0, body: null });
            return;
          }
          try {
            resolve({
              status: response.statusCode || 0,
              body: JSON.parse(text) as unknown,
            });
          } catch {
            reject(new Error("پاسخ هاب JSON معتبر نیست"));
          }
        });
      },
    );

    request.on("timeout", () => {
      request.destroy(new Error("زمان پاسخ هاب تمام شد"));
    });
    request.on("error", reject);
    if (payload) request.write(payload);
    request.end();
  });
}

export function errorMessage(error: unknown): string {
  if (error instanceof CertificatePinError) return error.message;
  if (error instanceof Error) {
    if (/ECONNREFUSED/.test(error.message)) return "هاب در دسترس نیست (اتصال رد شد)";
    if (/ENOTFOUND|EAI_AGAIN/.test(error.message)) return "آدرس هاب پیدا نشد";
    if (/ETIMEDOUT|timeout/i.test(error.message)) return "زمان اتصال به هاب تمام شد";
    return error.message;
  }
  return String(error);
}
