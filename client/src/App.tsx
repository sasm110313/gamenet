import { Component, useEffect, useMemo, useRef, useState, type ErrorInfo, type ReactNode } from "react";
import type {
  AnnouncementItem,
  CommandNotice,
  ConnectionPhase,
  GameItem,
  PublicState,
  RunningAppWindow,
} from "../shared/ipc";

type PowerAction = "shutdown" | "restart";

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("UI Uncaught Error:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center bg-space p-6 text-center text-pearl" dir="rtl">
          <div className="max-w-md rounded-2xl border border-danger/40 bg-card/90 p-8 shadow-2xl">
            <div className="mb-4 inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-danger/20 text-danger">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-8 w-8">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </div>
            <h1 className="text-xl font-bold text-pearl">خطای غیرمنتظره در رابط کاربری کلاینت</h1>
            <p className="mt-2 text-sm text-mist">
              یک خطای رندرینگ رخ داد اما هسته برنامه پایدار است. با دکمه زیر می‌توانید صفحه را بازیابی کنید.
            </p>
            {this.state.error && (
              <pre className="mt-4 max-h-32 overflow-auto rounded bg-space/80 p-2 text-left font-mono text-xs text-danger" dir="ltr">
                {this.state.error.message || String(this.state.error)}
              </pre>
            )}
            <div className="mt-6 flex flex-col gap-2">
              <button
                type="button"
                onClick={() => {
                  this.setState({ hasError: false, error: null });
                  window.location.reload();
                }}
                className="w-full rounded-xl bg-neon px-5 py-3 font-semibold text-space transition hover:bg-neon/90"
              >
                راه‌اندازی مجدد رابط کاربری (Reload)
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const PHASE: Record<ConnectionPhase, { label: string; dot: string; text: string }> = {
  unpaired: { label: "ثبت‌نشده", dot: "bg-mist", text: "text-mist" },
  connecting: { label: "در حال اتصال", dot: "bg-amber animate-pulse", text: "text-amber" },
  connected: { label: "متصل به هاب", dot: "bg-neon", text: "text-neon" },
  reconnecting: { label: "اتصال مجدد", dot: "bg-amber animate-pulse", text: "text-amber" },
  offline: { label: "آفلاین", dot: "bg-danger", text: "text-danger" },
};

const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";

function fa(value: number | string): string {
  return String(value).replace(/\d/g, (digit) => FA_DIGITS[Number(digit)]);
}

function duration(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.min(99, Math.floor(total / 3600));
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return fa([hours, minutes, seconds].map((part) => String(part).padStart(2, "0")).join(":"));
}

function useNow(active: boolean, monotonic = false): number {
  const [now, setNow] = useState(() => monotonic ? performance.now() : Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(monotonic ? performance.now() : Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active, monotonic]);
  return now;
}

function GamepadMark({ className = "" }: { className?: string }): JSX.Element {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className={className} aria-hidden="true">
      <path d="M6.5 7.5h11a4 4 0 0 1 3.9 4.9l-1 4.2a2.6 2.6 0 0 1-4.5 1.2L14.6 16H9.4l-1.3 1.8a2.6 2.6 0 0 1-4.5-1.2l-1-4.2a4 4 0 0 1 3.9-4.9Z" strokeLinejoin="round" />
      <path d="M8 10v3M6.5 11.5h3M15.5 11h.01M17.5 12.5h.01" strokeLinecap="round" />
    </svg>
  );
}

function LockIcon({ className = "" }: { className?: string }): JSX.Element {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className={className} aria-hidden="true">
      <rect x="4.5" y="10" width="15" height="10" rx="2.5" />
      <path d="M8 10V7.5a4 4 0 0 1 8 0V10M12 14v2.5" strokeLinecap="round" />
    </svg>
  );
}

function PowerIcon({ className = "" }: { className?: string }): JSX.Element {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className={className} aria-hidden="true">
      <path d="M12 3.5v8" strokeLinecap="round" />
      <path d="M6.6 6.8a8 8 0 1 0 10.8 0" strokeLinecap="round" />
    </svg>
  );
}

function RestartIcon({ className = "" }: { className?: string }): JSX.Element {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className={className} aria-hidden="true">
      <path d="M20 12a8 8 0 1 1-2.5-5.8" strokeLinecap="round" />
      <path d="M20 4.5V10h-5.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ExternalIcon({ className = "" }: { className?: string }): JSX.Element {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className={className} aria-hidden="true">
      <path d="M14 4h6v6M20 4l-8 8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M18 13.5V18a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4.5" strokeLinecap="round" />
    </svg>
  );
}

function MinimizeIcon({ className = "" }: { className?: string }): JSX.Element {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className={className} aria-hidden="true">
      <path d="M6 12h12" strokeLinecap="round" />
    </svg>
  );
}

function CloseIcon({ className = "" }: { className?: string }): JSX.Element {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className={className} aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
    </svg>
  );
}

function ShieldIcon({ className = "" }: { className?: string }): JSX.Element {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className={className} aria-hidden="true">
      <path d="M12 3.5 19 6v5.2c0 4.2-2.8 7.4-7 9.3-4.2-1.9-7-5.1-7-9.3V6l7-2.5Z" strokeLinejoin="round" />
      <path d="m9 12 2 2 4-4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function UserIcon({ className = "" }: { className?: string }): JSX.Element {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className={className} aria-hidden="true">
      <circle cx="12" cy="8" r="4" />
      <path d="M6 20v-1a6 6 0 0 1 12 0v1" strokeLinecap="round" />
    </svg>
  );
}

function WifiIcon({ className = "" }: { className?: string }): JSX.Element {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className={className} aria-hidden="true">
      <path d="M3.5 9.5a12.5 12.5 0 0 1 17 0M6.5 13a8 8 0 0 1 11 0M9.5 16.4a3.5 3.5 0 0 1 5 0" strokeLinecap="round" />
      <circle cx="12" cy="19.2" r="1" fill="currentColor" stroke="none" />
    </svg>
  );
}

function Spinner({ className = "" }: { className?: string }): JSX.Element {
  return (
    <svg viewBox="0 0 24 24" className={`animate-spin ${className}`} aria-hidden="true">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeOpacity="0.2" strokeWidth="2.5" />
      <path d="M21 12a9 9 0 0 0-9-9" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}

function StatusPill({ phase }: { phase: ConnectionPhase }): JSX.Element {
  const meta = PHASE[phase];
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-line/90 bg-panel/80 px-3.5 py-1.5 text-xs font-medium">
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
      <span className={meta.text}>{meta.label}</span>
    </span>
  );
}

function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-sm font-medium text-paper">
          {label}
        </label>
        {hint ? <span className="text-[11px] text-mist">{hint}</span> : null}
      </div>
      {children}
    </div>
  );
}

function PairingScreen({
  state,
  onPaired,
}: {
  state: PublicState;
  onPaired: (state: PublicState) => void;
}): JSX.Element {
  const [host, setHost] = useState(state.discoveredHost || "192.168.1.10");
  const [port, setPort] = useState(String(state.discoveredPort || 19443));
  const [stationMode, setStationMode] = useState<"number" | "custom">("number");
  const [stationNum, setStationNum] = useState("1");
  const [customName, setCustomName] = useState(state.suggestedName || "PC-01");
  const [code, setCode] = useState("");
  const [fingerprint, setFingerprint] = useState(state.discoveredFingerprint || "");
  const [fullPairingString, setFullPairingString] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(state.lastError || "");
  const [hostTouched, setHostTouched] = useState(false);

  useEffect(() => {
    if (state.lastError) setError(state.lastError);
  }, [state.lastError]);

  useEffect(() => {
    if (!hostTouched && state.discoveredHost) {
      setHost(state.discoveredHost);
      if (state.discoveredPort) setPort(String(state.discoveredPort));
      if (state.discoveredFingerprint) setFingerprint(state.discoveredFingerprint);
    }
  }, [state.discoveredHost, state.discoveredPort, state.discoveredFingerprint, hostTouched]);

  const effectiveStationName =
    stationMode === "number"
      ? `PC-${String(Math.max(1, Math.min(999, Number(stationNum) || 1))).padStart(2, "0")}`
      : customName.trim();

  async function submit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (busy) return;
    setError("");

    const trimmedPairing = fullPairingString.trim();
    const cleanHost = host.trim();
    const cleanPort = Number(port) || 19443;

    if (!trimmedPairing && !cleanHost) {
      setError("آدرس IP سرور هاب را وارد کنید");
      return;
    }
    if (!effectiveStationName) {
      setError("شماره یا نام ایستگاه را مشخص کنید");
      return;
    }

    setBusy(true);
    try {
      const result = await window.gamenet.pair(
        trimmedPairing.includes("#")
          ? {
              pairing: trimmedPairing,
              code: code.trim() || "LAN_AUTO",
              name: effectiveStationName,
            }
          : {
              host: cleanHost,
              port: cleanPort,
              fingerprint: fingerprint.trim(),
              code: code.trim() || "LAN_AUTO",
              name: effectiveStationName,
            },
      );
      if (result.ok) {
        onPaired(result.state);
      } else {
        setError(result.error);
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "ثبت دستگاه ناموفق بود");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="fade-up mx-auto grid w-full max-w-5xl gap-5 lg:grid-cols-[0.95fr_1.15fr]">
      <aside className="panel relative flex flex-col justify-between overflow-hidden p-7">
        <div className="pointer-events-none absolute -left-24 -top-24 h-64 w-64 rounded-full pro-glow " />
        <div className="relative">
          <span className="chip">
            <ShieldIcon className="h-3.5 w-3.5" />
            راه‌اندازی اولیه سیستم
          </span>
          <h1 className="mt-5 text-2xl font-bold leading-snug text-paper sm:text-3xl">
            این سیستم را به
            <span className="text-neon"> هاب سالن </span>
            متصل کنید
          </h1>
          <p className="mt-3 text-xs leading-7 text-mist">
            شماره سیستم (ایستگاه) و آدرس IP سرور مرکزی را مشخص کنید. گواهی TLS هاب
            به‌صورت خودکار دریافت و پین می‌شود.
          </p>
        </div>

        <div className="relative mt-6 space-y-3 text-xs">
          <div className="rounded-xl border border-line/70 bg-ink/50 p-3.5 space-y-1.5">
            <p className="text-[10px] uppercase tracking-wider text-mist">مشخصات سخت‌افزاری این سیستم</p>
            <div className="flex justify-between">
              <span className="text-mist">نام ویندوز:</span>
              <span className="font-mono text-paper" dir="ltr">{state.hostname || "—"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-mist">مک‌آدرس (MAC):</span>
              <span className="font-mono text-paper" dir="ltr">{state.macAddress || "—"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-mist">نسخه کلاینت:</span>
              <span className="font-mono text-neon" dir="ltr">v{state.appVersion}</span>
            </div>
          </div>

          {state.discoveredHost ? (
            <div className="rounded-xl border border-neon/40 bg-neon/10 p-3.5 text-neon">
              <div className="flex items-center justify-between gap-2">
                <span className="font-bold">✓ سرور هاب در شبکه پیدا شد</span>
                <button
                  type="button"
                  onClick={() => {
                    setHost(state.discoveredHost || "");
                    setPort(String(state.discoveredPort || 19443));
                    setFingerprint(state.discoveredFingerprint || "");
                    setHostTouched(false);
                  }}
                  className="underline text-[11px] text-paper hover:text-neon"
                >
                  استفاده از این سرور
                </button>
              </div>
              <p className="mt-1 font-mono text-[11px] text-paper/90" dir="ltr">
                {state.discoveredHost}:{state.discoveredPort || 19443}
                {state.discoveredHubName ? ` (${state.discoveredHubName})` : ""}
              </p>
            </div>
          ) : (
            <div className="rounded-xl border border-line/60 bg-ink/40 p-3.5 text-mist leading-6">
              اگر سرور در شبکه پیدا نشد، آدرس IP کامپیوتر سرور (هاب) را در کادر مقابل وارد کنید.
            </div>
          )}
        </div>

        <div className="relative mt-6 flex items-start gap-2.5 rounded-xl border border-line/80 bg-ink/50 p-3.5 text-[11px] leading-5 text-mist">
          <ShieldIcon className="mt-0.5 h-4 w-4 shrink-0 text-neon" />
          <p>
            در هر زمان پس از ثبت نیز می‌توانید با زدن کلید <strong className="text-paper">Esc</strong> و ورود ادمین،
            شماره سیستم یا IP سرور را تغییر دهید.
          </p>
        </div>
      </aside>

      <form onSubmit={submit} className="panel flex flex-col p-7" noValidate>
        <div>
          <p className="text-xs font-medium text-mist">تنظیمات اولیه کلاینت</p>
          <h2 className="mt-1 text-xl font-bold">تعیین IP سرور و شماره ایستگاه</h2>
        </div>

        <div className="mt-5 space-y-4">
          <div className="grid gap-3 sm:grid-cols-[1.5fr_0.7fr]">
            <Field id="hub-host" label="آدرس IP سرور هاب" hint="مثلاً 192.168.1.10">
              <input
                id="hub-host"
                className="field font-mono text-sm"
                dir="ltr"
                autoComplete="off"
                spellCheck={false}
                placeholder="192.168.1.10"
                value={host}
                onChange={(event) => {
                  setHostTouched(true);
                  setHost(event.target.value);
                }}
                autoFocus
                disabled={busy}
              />
            </Field>
            <Field id="hub-port" label="پورت سرور">
              <input
                id="hub-port"
                type="number"
                className="field font-mono text-sm text-center"
                dir="ltr"
                value={port}
                onChange={(event) => {
                  setHostTouched(true);
                  setPort(event.target.value);
                }}
                disabled={busy}
              />
            </Field>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between gap-2">
              <label className="text-sm font-medium text-paper">
                این سیستم شماره چند است؟
              </label>
              <button
                type="button"
                onClick={() => setStationMode(stationMode === "number" ? "custom" : "number")}
                className="text-[11px] text-neon hover:underline"
              >
                {stationMode === "number" ? "ورود نام دلخواه (مثل VIP)" : "انتخاب عددی ایستگاه"}
              </button>
            </div>

            {stationMode === "number" ? (
              <div className="space-y-2.5">
                <div className="grid grid-cols-5 gap-1.5 sm:grid-cols-10">
                  {Array.from({ length: 10 }, (_, i) => String(i + 1)).map((n) => (
                    <button
                      key={n}
                      type="button"
                      disabled={busy}
                      onClick={() => setStationNum(n)}
                      className={`rounded-xl border py-2 font-mono text-xs font-bold transition-all ${
                        stationNum === n
                          ? "border-neon bg-neon/20 text-neon shadow-glow"
                          : "border-line/70 bg-ink/50 text-mist hover:border-line hover:text-paper"
                      }`}
                    >
                      {fa(n)}
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-3">
                  <input
                    id="station-number-input"
                    type="number"
                    min={1}
                    max={999}
                    className="field w-28 text-center font-mono text-sm"
                    dir="ltr"
                    value={stationNum}
                    onChange={(event) => setStationNum(event.target.value)}
                    disabled={busy}
                  />
                  <span className="text-xs text-mist">
                    ثبت در سرور با نام: <strong className="font-mono text-neon" dir="ltr">{effectiveStationName}</strong>
                  </span>
                </div>
              </div>
            ) : (
              <input
                id="custom-station-name"
                className="field text-sm"
                dir="ltr"
                placeholder="مثلاً PC-11 یا VIP-01"
                value={customName}
                onChange={(event) => setCustomName(event.target.value)}
                disabled={busy}
                maxLength={80}
              />
            )}
          </div>

          <details className="rounded-xl border border-line/60 bg-ink/30 p-3 text-xs">
            <summary className="cursor-pointer font-medium text-mist hover:text-paper select-none">
              تنظیمات پیشرفته (کد ثبت یک‌بارمصرف یا اثر انگشت گواهی)
            </summary>
            <div className="mt-3 space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field id="code" label="کد ثبت" hint="اختیاری">
                  <input
                    id="code"
                    className="field text-center font-mono text-xs tracking-[0.2em]"
                    dir="ltr"
                    autoComplete="off"
                    spellCheck={false}
                    placeholder="LAN_AUTO"
                    value={code}
                    onChange={(event) => setCode(event.target.value.toUpperCase())}
                    disabled={busy}
                    maxLength={64}
                  />
                </Field>
                <Field id="fp" label="اثر انگشت SHA-256" hint="اختیاری">
                  <input
                    id="fp"
                    className="field font-mono text-[11px]"
                    dir="ltr"
                    autoComplete="off"
                    placeholder="دریافت خودکار از سرور"
                    value={fingerprint}
                    onChange={(event) => setFingerprint(event.target.value)}
                    disabled={busy}
                  />
                </Field>
              </div>
              <Field id="pairing-str" label="رشته اتصال کامل (اختیاری)" hint="host:port#fingerprint">
                <input
                  id="pairing-str"
                  className="field font-mono text-[11px]"
                  dir="ltr"
                  autoComplete="off"
                  placeholder="192.168.1.10:19443#A1B2..."
                  value={fullPairingString}
                  onChange={(event) => setFullPairingString(event.target.value)}
                  disabled={busy}
                />
              </Field>
            </div>
          </details>
        </div>

        {error ? (
          <div role="alert" aria-live="polite" className="mt-4 rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-xs leading-6 text-danger flex items-center justify-between gap-2">
            <span>{error}</span>
            <button
              type="button"
              className="text-[11px] underline text-mist hover:text-white shrink-0 cursor-pointer"
              onClick={() => {
                void window.gamenet.copyText(error);
              }}
            >
              📋 کپی خطا
            </button>
          </div>
        ) : null}

        <div className="mt-auto pt-5">
          <button type="submit" className="btn btn-primary w-full" disabled={busy}>
            {busy ? <Spinner className="h-4 w-4" /> : <WifiIcon className="h-4 w-4" />}
            {busy ? "در حال اتصال و ثبت…" : `اتصال و ثبت به عنوان ${effectiveStationName}`}
          </button>
        </div>
      </form>
    </section>
  );
}

function OfflineBanner({ state }: { state: PublicState }): JSX.Element | null {
  if (state.phase === "connected") return null;
  const connecting = state.phase === "connecting" || state.phase === "reconnecting";
  return (
    <div className="mt-5 flex w-full items-start gap-3 rounded-2xl border border-amber/25 bg-amber/5 px-4 py-2.5 text-right">
      <span className="mt-1 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-amber/10 text-amber">
        {connecting ? <Spinner className="h-4 w-4" /> : <WifiIcon className="h-4 w-4" />}
      </span>
      <div className="min-w-0">
        <p className="text-xs font-semibold text-amber">
          {connecting ? "ارتباط با هاب در حال برقراری است" : "ارتباط با هاب قطع است"}
        </p>
        <p className="mt-1 break-words text-[11px] leading-5 text-mist">
          {state.lastError || "تلاش خودکار برای اتصال ادامه دارد."}
        </p>
      </div>
    </div>
  );
}

function PowerConfirmModal({
  action,
  busy,
  onCancel,
  onConfirm,
}: {
  action: PowerAction | null;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}): JSX.Element | null {
  if (!action) return null;
  const shutdown = action === "shutdown";
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-ink/90 p-4">
      <div className="panel w-full max-w-sm p-6 space-y-4">
        <div className="flex items-center gap-3">
          <span className={`grid h-11 w-11 place-items-center rounded-xl text-xl ${shutdown ? "bg-danger/15 text-danger" : "bg-amber/15 text-amber"}`}>
            {shutdown ? <PowerIcon className="h-5 w-5" /> : <RestartIcon className="h-5 w-5" />}
          </span>
          <div>
            <h3 className="text-base font-bold text-paper">
              {shutdown ? "خاموش کردن سیستم؟" : "راه‌اندازی مجدد سیستم؟"}
            </h3>
            <p className="mt-1 text-[11px] leading-5 text-mist">
              {shutdown
                ? "نشست بازی پایان می‌یابد، هزینه دقیق محاسبه و سیستم خاموش می‌شود."
                : "نشست بازی پایان می‌یابد، هزینه دقیق محاسبه و سیستم ری‌استارت می‌شود."}
            </p>
          </div>
        </div>
        <div className="flex gap-2 pt-1">
          <button type="button" className="btn btn-ghost flex-1 text-xs py-2.5" onClick={onCancel} disabled={busy}>
            انصراف
          </button>
          <button
            type="button"
            className={`btn flex-1 text-xs py-2.5 justify-center ${shutdown ? "bg-danger text-white hover:bg-danger/90" : "btn-solid"}`}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? <Spinner className="h-4 w-4" /> : shutdown ? "بله، خاموش شود" : "بله، ری‌استارت شود"}
          </button>
        </div>
      </div>
    </div>
  );
}

function LockedScreen({
  state,
  busy,
  onPreview,
  onPower,
}: {
  state: PublicState;
  busy: boolean;
  onPreview: () => void;
  onPower: (action: PowerAction) => void;
}): JSX.Element {
  const ready = state.phase === "connected";
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [loginError, setLoginError] = useState("");
  const [showAnnouncementsModal, setShowAnnouncementsModal] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setLoginError("لطفاً نام کاربری و رمز عبور را وارد کنید.");
      return;
    }
    setLoginError("");
    setSubmitting(true);
    try {
      const res = await window.gamenet.userLogin({ username: username.trim(), password });
      if (!res.ok) {
        setLoginError(res.error || "نام کاربری یا رمز عبور اشتباه است.");
      }
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : "خطا در برقراری ارتباط با هاب");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="fade-up mx-auto w-full max-w-4xl">
      <div className="grid gap-6 md:grid-cols-2">
        {/* Left: Station status info */}
        <div className="panel relative flex flex-col justify-between overflow-hidden p-6 sm:p-8">
          <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-l from-transparent via-neon/60 to-transparent" />
          <div className="pointer-events-none absolute -left-20 -top-20 h-64 w-64 rounded-full pro-glow " />

          <div>
            <div className="flex items-center justify-between">
              <span className="chip">
                <span className="h-2 w-2 rounded-full bg-neon animate-pulse" />
                {state.deviceName || "رایانه بازی"}
              </span>
              <span className="text-xs text-mist">{state.hubName || "هاب سالن"}</span>
            </div>

            <div className="mt-8 text-center">
              <div className="mx-auto grid h-24 w-24 place-items-center rounded-2xl border border-line/70 bg-ink/60 shadow-inner">
                <LockIcon className="h-10 w-10 text-mist" />
              </div>
              <h1 className="mt-4 text-2xl font-bold">این رایانه قفل است</h1>
              <p className="mt-2 text-xs leading-6 text-mist">
                برای شروع بازی، نام کاربری و رمز عبور خود را وارد کنید یا از مسئول سالن بخواهید بازی را باز کند.
              </p>
            </div>

            <OfflineBanner state={state} />
          </div>

          <div className="mt-6 border-t border-line/60 pt-4">
            <div className="grid grid-cols-2 gap-2 text-center text-xs">
              <div className="rounded-xl border border-line/60 bg-ink/40 p-2.5">
                <span className="text-[10px] text-mist block">وضعیت شبکه</span>
                <span className="font-semibold text-neon mt-0.5 block">{PHASE[state.phase].label}</span>
              </div>
              <div className="rounded-xl border border-line/60 bg-ink/40 p-2.5">
                <span className="text-[10px] text-mist block">تعرفه ساعت</span>
                <span className="font-semibold text-paper mt-0.5 block">بر اساس حساب کاربری</span>
              </div>
            </div>

            {state.canPreview && (
              <button
                type="button"
                className="mt-3 w-full btn btn-ghost text-xs py-2"
                onClick={onPreview}
                disabled={!ready || busy}
              >
                پیش‌نمایش محیط بازی (توسعه)
              </button>
            )}

            <div className="mt-4 border-t border-line/60 pt-3">
              <p className="mb-2 text-[10px] font-medium uppercase tracking-wider text-mist">ابزار مسئول سالن</p>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  className="btn btn-ghost text-[11px] py-2"
                  onClick={() => onPower("restart")}
                  disabled={busy}
                >
                  <RestartIcon className="h-4 w-4" /> ری‌استارت سیستم
                </button>
                <button
                  type="button"
                  className="btn btn-ghost text-[11px] py-2 border-danger/30 text-danger hover:bg-danger/10"
                  onClick={() => onPower("shutdown")}
                  disabled={busy}
                >
                  <PowerIcon className="h-4 w-4" /> خاموش کردن
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Right: Gamer Login Form */}
        <form onSubmit={handleLogin} className="panel relative flex flex-col justify-between overflow-hidden p-6 sm:p-8" noValidate>
          <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-l from-transparent via-neon/60 to-transparent" />

          <div>
            <div className="flex items-center gap-3">
              <span className="grid h-10 w-10 place-items-center rounded-xl bg-neon/10 text-neon border border-neon/25">
                <UserIcon className="h-5 w-5" />
              </span>
              <div>
                <h2 className="text-lg font-bold text-paper">ورود گیمر به سیستم</h2>
                <p className="text-[11px] text-mist">محاسبه دقیق زمان و کسر خودکار از کیف پول</p>
              </div>
            </div>

            <div className="mt-6 space-y-4">
              <Field id="login-username" label="کد ۴ تا ۶ رقمی ورود یا شماره همراه">
                <input
                  id="login-username"
                  className="field text-sm font-mono tracking-wider"
                  dir="ltr"
                  autoComplete="username"
                  placeholder="مثلاً ۱۲۳۴۵ یا 0912..."
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  disabled={!ready || submitting}
                  autoFocus
                />
              </Field>

              <Field id="login-password" label="رمز عبور (پیش‌فرض: شماره موبایل)">
                <input
                  id="login-password"
                  type="password"
                  className="field text-sm font-mono"
                  dir="ltr"
                  autoComplete="current-password"
                  placeholder="رمز عبور یا شماره موبایل"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={!ready || submitting}
                />
              </Field>
            </div>

            {loginError ? (
              <div role="alert" className="mt-4 rounded-xl border border-danger/30 bg-danger/10 p-3 text-xs leading-5 text-danger flex items-center justify-between gap-2">
                <span>{loginError}</span>
                <button
                  type="button"
                  className="text-[11px] underline text-mist hover:text-white shrink-0 cursor-pointer"
                  onClick={() => {
                    void window.gamenet.copyText(loginError);
                  }}
                >
                  📋 کپی خطا
                </button>
              </div>
            ) : null}
          </div>

          <div className="mt-6 pt-4 border-t border-line/60">
            <button
              type="submit"
              className="btn btn-primary w-full text-sm py-3"
              disabled={!ready || submitting}
            >
              {submitting ? <Spinner className="h-4 w-4" /> : <GamepadMark className="h-4 w-4" />}
              {submitting ? "در حال اعتبارسنجی…" : "ورود و شروع بازی"}
            </button>
            <p className="mt-3 text-center text-[11px] text-mist leading-5">
              حساب کاربری ندارید یا شارژ تمام شده؟ به مسئول صندوق سالن مراجعه کنید.
            </p>
          </div>
        </form>
      </div>

      {/* Salon Announcements Banner */}
      <SalonAnnouncementsBanner
        announcements={state.announcements}
        onOpenModal={() => setShowAnnouncementsModal(true)}
      />

      {showAnnouncementsModal && (
        <AnnouncementsModal
          announcements={state.announcements}
          onClose={() => setShowAnnouncementsModal(false)}
        />
      )}
    </section>
  );
}

function AdminEscapeModal({
  isOpen,
  state,
  onStateChange,
  onClose,
}: {
  isOpen: boolean;
  state: PublicState | null;
  onStateChange: (next: PublicState) => void;
  onClose: () => void;
}): JSX.Element | null {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [unlocked, setUnlocked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  // Editable connection & station settings (populated when modal opens)
  const [editHost, setEditHost] = useState("");
  const [editPort, setEditPort] = useState("19443");
  const [editStationName, setEditStationName] = useState("PC-01");
  const [editIdleMinutes, setEditIdleMinutes] = useState("15");
  const [editFingerprint, setEditFingerprint] = useState("");
  const [editCode, setEditCode] = useState("");

  useEffect(() => {
    if (!isOpen) {
      setUnlocked(false);
      setPassword("");
      setError(null);
      setNotice(null);
      setConfirmReset(false);
      return;
    }
    const rawHostPort = state?.pairingHost || "";
    const parts = rawHostPort.split(":");
    setEditHost(parts[0] || state?.discoveredHost || "192.168.1.10");
    setEditPort(parts[1] || String(state?.discoveredPort || 19443));
    setEditStationName(state?.deviceName || state?.suggestedName || "PC-01");
    setEditIdleMinutes(String(state?.idleShutdownMinutes ?? 15));
    setEditFingerprint("");
    setEditCode("");
  }, [isOpen]);

  if (!isOpen) return null;

  const verifyAdmin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await window.gamenet.adminUnlock({
        username: username.trim(),
        password,
        action: "verify",
      });
      if (!res.ok) {
        setError(res.error || "نام کاربری یا رمز عبور ادمین نادرست است.");
        return;
      }
      setUnlocked(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا در بررسی دسترسی ادمین");
    } finally {
      setBusy(false);
    }
  };

  const handleWindowsAction = async (action: "explorer" | "quit") => {
    setError(null);
    setBusy(true);
    try {
      const res = await window.gamenet.adminUnlock({
        username: username.trim(),
        password,
        action,
      });
      if (!res.ok) {
        setError(res.error || "مشخصات مدیر نادرست است.");
        return;
      }
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا در ارتباط با سرور");
    } finally {
      setBusy(false);
    }
  };

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setNotice(null);
    if (!editHost.trim()) {
      setError("آدرس IP سرور هاب نمی‌تواند خالی باشد.");
      return;
    }
    if (!editStationName.trim()) {
      setError("شماره یا نام ایستگاه نمی‌تواند خالی باشد.");
      return;
    }
    setBusy(true);
    try {
      const res = await window.gamenet.reconfigureConnection({
        username: username.trim(),
        password,
        host: editHost.trim(),
        port: Number(editPort) || 19443,
        fingerprint: editFingerprint.trim() || undefined,
        code: editCode.trim() || undefined,
        name: editStationName.trim(),
        idleShutdownMinutes: Number(editIdleMinutes) || 0,
      });
      if (!res.ok) {
        setError(res.error || "ذخیره تنظیمات اتصال ناموفق بود.");
        return;
      }
      onStateChange(res.state);
      setNotice("تنظیمات با موفقیت روی سیستم و سرور اعمال شد.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا در ذخیره تنظیمات");
    } finally {
      setBusy(false);
    }
  };

  const handleResetClient = async () => {
    setError(null);
    setBusy(true);
    try {
      const res = await window.gamenet.resetClientPairing({
        username: username.trim(),
        password,
      });
      if (!res.ok) {
        setError(res.error || "ریست کلاینت انجام نشد.");
        return;
      }
      onStateChange(res.state);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا در ریست کلاینت");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink/85">
      <div className="panel max-w-xl w-full p-6 shadow-2xl border-neon/40 space-y-4 max-h-[92vh] overflow-y-auto">
        <div className="flex items-center justify-between pb-3 border-b border-line/60">
          <div className="flex items-center gap-2.5">
            <span className="text-2xl">🛡️</span>
            <div>
              <h2 className="text-base font-bold text-paper">
                {unlocked ? "تنظیمات ادمین و مدیریت سیستم" : "ورود ادمین سیستم (Esc)"}
              </h2>
              <p className="text-[11px] text-mist">
                {unlocked
                  ? "تغییر IP سرور، شماره ایستگاه، زمان خاموشی و خروج از کیوسک"
                  : "برای دسترسی به تنظیمات شبکه، شماره سیستم یا خروج، رمز مدیر را وارد کنید"}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-7 h-7 rounded-lg grid place-items-center bg-ink/60 text-mist hover:text-paper border border-line/60"
          >
            ✕
          </button>
        </div>

        {error && (
          <div className="p-2.5 rounded-lg border border-danger/40 bg-danger/10 text-danger text-xs flex items-center gap-2">
            <span>⚠️</span>
            <span>{error}</span>
          </div>
        )}

        {notice && (
          <div className="p-2.5 rounded-lg border border-neon/40 bg-neon/10 text-neon text-xs flex items-center gap-2">
            <span>✓</span>
            <span>{notice}</span>
          </div>
        )}

        {!unlocked ? (
          <form onSubmit={verifyAdmin} className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-mist mb-1">نام کاربری ادمین:</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full rounded-lg border border-line bg-panel px-3 py-2 text-xs text-paper focus:border-neon focus:outline-none"
                dir="ltr"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-mist mb-1">رمز عبور ادمین:</label>
              <input
                type="password"
                autoFocus
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="رمز عبور مدیر سالن"
                className="w-full rounded-lg border border-line bg-panel px-3 py-2 text-xs text-paper focus:border-neon focus:outline-none"
                dir="ltr"
              />
            </div>

            <div className="pt-2 flex items-center gap-2">
              <button
                type="submit"
                disabled={busy || !password}
                className="flex-1 btn btn-primary text-xs py-2.5 flex items-center justify-center gap-2"
              >
                {busy ? <Spinner className="h-4 w-4" /> : <span>🔓</span>}
                ورود به تنظیمات ادمین
              </button>
              <button
                type="button"
                onClick={onClose}
                className="btn btn-ghost text-xs py-2.5 px-4"
              >
                انصراف
              </button>
            </div>
          </form>
        ) : (
          <div className="space-y-4">
            {/* System Hardware & Connection Info Strip */}
            <div className="rounded-xl border border-line/70 bg-ink/50 p-3 grid grid-cols-2 sm:grid-cols-3 gap-2.5 text-[11px]">
              <div>
                <span className="text-mist block">نام ایستگاه فعلی</span>
                <span className="font-mono font-bold text-neon" dir="ltr">{state?.deviceName || "ثبت‌نشده"}</span>
              </div>
              <div>
                <span className="text-mist block">سرور فعلی</span>
                <span className="font-mono font-bold text-paper" dir="ltr">{state?.pairingHost || "—"}</span>
              </div>
              <div>
                <span className="text-mist block">نام کامپیوتر (Host)</span>
                <span className="font-mono text-paper" dir="ltr">{state?.hostname || "—"}</span>
              </div>
              <div>
                <span className="text-mist block">مک‌آدرس (MAC)</span>
                <span className="font-mono text-paper" dir="ltr">{state?.macAddress || "—"}</span>
              </div>
              <div>
                <span className="text-mist block">نسخه کلاینت</span>
                <span className="font-mono text-paper" dir="ltr">v{state?.appVersion || "0.2.2"}</span>
              </div>
              <div>
                <span className="text-mist block">وضعیت</span>
                <span className="font-bold text-paper">{state ? PHASE[state.phase].label : "—"}</span>
              </div>
            </div>

            {/* Reconfigure Server IP & Station Number */}
            <form onSubmit={handleSaveSettings} className="space-y-3 rounded-xl border border-line/60 bg-ink/30 p-4">
              <h3 className="text-xs font-bold text-paper flex items-center gap-1.5">
                <span>🌐</span> تنظیم IP سرور، شماره سیستم و زمان خاموشی
              </h3>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                <div className="sm:col-span-2">
                  <label className="block text-[11px] text-mist mb-1">آدرس IP سرور هاب:</label>
                  <input
                    type="text"
                    value={editHost}
                    onChange={(e) => setEditHost(e.target.value)}
                    className="w-full rounded-lg border border-line bg-panel px-3 py-1.5 font-mono text-xs text-paper focus:border-neon focus:outline-none"
                    dir="ltr"
                    placeholder="192.168.1.10"
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-mist mb-1">پورت هاب:</label>
                  <input
                    type="number"
                    value={editPort}
                    onChange={(e) => setEditPort(e.target.value)}
                    className="w-full rounded-lg border border-line bg-panel px-3 py-1.5 font-mono text-xs text-paper focus:border-neon focus:outline-none"
                    dir="ltr"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                <div>
                  <label className="block text-[11px] text-mist mb-1">شماره یا نام سیستم (مثلاً ۱ یا PC-03):</label>
                  <input
                    type="text"
                    value={editStationName}
                    onChange={(e) => setEditStationName(e.target.value)}
                    className="w-full rounded-lg border border-line bg-panel px-3 py-1.5 font-mono text-xs text-paper focus:border-neon focus:outline-none"
                    dir="ltr"
                    placeholder="PC-01"
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-mist mb-1">خاموشی خودکار بی‌کاری (دقیقه، ۰=خاموش):</label>
                  <input
                    type="number"
                    min={0}
                    max={720}
                    value={editIdleMinutes}
                    onChange={(e) => setEditIdleMinutes(e.target.value)}
                    className="w-full rounded-lg border border-line bg-panel px-3 py-1.5 font-mono text-xs text-paper focus:border-neon focus:outline-none"
                    dir="ltr"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                <div>
                  <label className="block text-[11px] text-mist mb-1">کد ثبت (اختیاری - خالی = خودکار):</label>
                  <input
                    type="text"
                    value={editCode}
                    onChange={(e) => setEditCode(e.target.value.toUpperCase())}
                    className="w-full rounded-lg border border-line bg-panel px-3 py-1.5 font-mono text-xs text-paper focus:border-neon focus:outline-none"
                    dir="ltr"
                    placeholder="LAN_AUTO"
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-mist mb-1">اثر انگشت گواهی (خالی = دریافت خودکار):</label>
                  <input
                    type="text"
                    value={editFingerprint}
                    onChange={(e) => setEditFingerprint(e.target.value)}
                    className="w-full rounded-lg border border-line bg-panel px-3 py-1.5 font-mono text-[11px] text-paper focus:border-neon focus:outline-none"
                    dir="ltr"
                    placeholder="SHA-256 خودکار"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={busy}
                className="w-full btn btn-primary text-xs py-2 flex items-center justify-center gap-2"
              >
                {busy ? <Spinner className="h-4 w-4" /> : <span>💾</span>}
                ذخیره تغییرات و اتصال مجدد به سرور
              </button>
            </form>

            {/* System Actions */}
            <div className="space-y-2 pt-2 border-t border-line/60">
              <button
                type="button"
                disabled={busy}
                onClick={() => handleWindowsAction("explorer")}
                className="w-full btn btn-ghost text-xs py-2.5 flex items-center justify-center gap-2 border-neon/40 text-neon hover:bg-neon/10"
              >
                <span>🪟</span>
                خروج از کیوسک و باز کردن Windows Explorer
              </button>

              {!confirmReset ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setConfirmReset(true)}
                  className="w-full btn btn-ghost text-xs py-2 flex items-center justify-center gap-2 text-amber hover:bg-amber/10 border-amber/30"
                >
                  <RestartIcon className="h-4 w-4" />
                  حذف اتصال و ریست کلاینت (بازگشت به صفحه ثبت اولیه)
                </button>
              ) : (
                <div className="rounded-xl border border-amber/50 bg-amber/10 p-3 space-y-2">
                  <p className="text-xs text-amber font-medium">
                    آیا مطمئنید؟ این سیستم از سرور جدا شده و به صفحه اول برمی‌گردد تا ایستگاه جدید ثبت شود.
                  </p>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={handleResetClient}
                      className="flex-1 btn text-xs py-1.5 bg-amber text-ink font-bold hover:bg-amber/90"
                    >
                      بله، ریست و حذف اتصال شود
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmReset(false)}
                      className="btn btn-ghost text-xs py-1.5 px-3"
                    >
                      انصراف
                    </button>
                  </div>
                </div>
              )}

              <button
                type="button"
                disabled={busy}
                onClick={() => handleWindowsAction("quit")}
                className="w-full btn btn-ghost text-xs py-2 flex items-center justify-center gap-2 text-danger hover:bg-danger/10 border-danger/30"
              >
                <span>🚪</span>
                بستن کامل برنامه کلاینت (Quit)
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function SalonAnnouncementsBanner({
  announcements,
  onOpenModal,
}: {
  announcements?: AnnouncementItem[];
  onOpenModal: () => void;
}): JSX.Element {
  const items = announcements && announcements.length > 0 ? announcements : [
    {
      id: "default_welcome",
      title: "به بازی سرای رهرو خوش آمدید",
      content: "ساعات خوش و پرهیجانی را برای شما آرزومندیم. لطفاً در حفظ نظم، نظافت و نگهداری تجهیزات سالن کوشا باشید. برای شارژ حساب به مسئول سالن مراجعه فرمایید.",
      type: "info" as const,
      author: "مدیریت بازی سرای رهرو",
    }
  ];

  const [activeIndex, setActiveIndex] = useState(0);
  const current = items[activeIndex % items.length];

  const typeConfig: Record<string, { border: string; bg: string; badge: string; icon: string; label: string }> = {
    info: { border: "border-neon/30", bg: "bg-neon/[0.04]", badge: "border-neon/40 text-neon bg-neon/10", icon: "📢", label: "اطلاعیه سالن" },
    success: { border: "border-emerald-500/40", bg: "bg-emerald-500/[0.04]", badge: "border-emerald-500/40 text-emerald-400 bg-emerald-500/10", icon: "🏆", label: "مسابقات و رویداد" },
    warning: { border: "border-amber/40", bg: "bg-amber/[0.04]", badge: "border-amber/40 text-amber bg-amber/10", icon: "⚠️", label: "تذکر سالن" },
    danger: { border: "border-danger/40", bg: "bg-danger/[0.04]", badge: "border-danger/40 text-danger bg-danger/10", icon: "🚨", label: "فوری و مهم" },
  };

  const style = typeConfig[current.type || "info"] || typeConfig.info;

  return (
    <div className={`panel p-4 flex flex-col sm:flex-row items-center justify-between gap-4 mt-4 transition-all duration-300 ${style.border} ${style.bg}`}>
      <div className="flex items-start gap-3.5 w-full">
        <div className="h-12 w-12 rounded-xl bg-ink/70 border border-line/60 flex items-center justify-center text-2xl shrink-0 shadow">
          {style.icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className={`text-[11px] font-bold px-2 py-0.5 rounded-md border ${style.badge}`}>
              {style.label}
            </span>
            <span className="text-xs font-bold text-paper truncate">
              {current.title}
            </span>
            {items.length > 1 && (
              <span className="text-[10px] text-mist bg-ink/80 px-1.5 py-0.2 rounded border border-line/50">
                {fa(activeIndex + 1)} از {fa(items.length)}
              </span>
            )}
          </div>
          <p className="text-xs text-mist font-medium leading-relaxed line-clamp-2">
            {current.content}
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2 shrink-0 w-full sm:w-auto justify-between sm:justify-end">
        {items.length > 1 && (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setActiveIndex((prev) => (prev - 1 + items.length) % items.length)}
              className="h-7 w-7 rounded-lg bg-ink/80 border border-line/60 text-xs text-mist hover:text-paper hover:border-line flex items-center justify-center transition-colors"
              title="پیام قبلی"
            >
              ❮
            </button>
            <button
              type="button"
              onClick={() => setActiveIndex((prev) => (prev + 1) % items.length)}
              className="h-7 w-7 rounded-lg bg-ink/80 border border-line/60 text-xs text-mist hover:text-paper hover:border-line flex items-center justify-center transition-colors"
              title="پیام بعدی"
            >
              ❯
            </button>
          </div>
        )}
        <button
          type="button"
          onClick={onOpenModal}
          className="btn btn-ghost text-xs py-1.5 px-3 border-line/80 hover:border-neon text-paper flex items-center gap-1.5"
        >
          <span>👁️</span>
          مشاهده پیام‌ها
        </button>
      </div>
    </div>
  );
}

function AnnouncementsModal({
  announcements,
  onClose,
}: {
  announcements?: AnnouncementItem[];
  onClose: () => void;
}): JSX.Element {
  const items = announcements && announcements.length > 0 ? announcements : [
    {
      id: "default_welcome",
      title: "به بازی سرای رهرو خوش آمدید",
      content: "ساعات خوش و پرهیجانی را برای شما عزیزان آرزومندیم. لطفاً در حفظ نظافت سالن، رعایت آرامش و نگهداری صحیح از تجهیزات و دسته‌ها کوشا باشید. در صورت نیاز به راهنمایی، شارژ حساب یا سفارش بوفه به مسئول سالن مراجعه فرمایید.",
      type: "info" as const,
      author: "مدیریت بازی سرای رهرو",
    }
  ];

  const typeConfig: Record<string, { border: string; bg: string; badge: string; icon: string; label: string }> = {
    info: { border: "border-neon/40", bg: "bg-neon/[0.03]", badge: "border-neon/40 text-neon bg-neon/10", icon: "📢", label: "اطلاع‌رسانی" },
    success: { border: "border-emerald-500/40", bg: "bg-emerald-500/[0.03]", badge: "border-emerald-500/40 text-emerald-400 bg-emerald-500/10", icon: "🏆", label: "مسابقات و رویداد" },
    warning: { border: "border-amber/40", bg: "bg-amber/[0.03]", badge: "border-amber/40 text-amber bg-amber/10", icon: "⚠️", label: "تذکر سالن" },
    danger: { border: "border-danger/40", bg: "bg-danger/[0.03]", badge: "border-danger/40 text-danger bg-danger/10", icon: "🚨", label: "فوری و اخطار" },
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/85 p-4 animate-in fade-in duration-200">
      <div className="panel max-w-xl w-full p-6 shadow-2xl border border-line/80 relative flex flex-col max-h-[85vh]">
        <div className="flex items-center justify-between pb-4 border-b border-line/60">
          <div className="flex items-center gap-2.5">
            <span className="text-2xl">📢</span>
            <div>
              <h3 className="text-base font-bold text-paper">تابلو اطلاعیه‌ها و پیام‌های سالن</h3>
              <p className="text-[11px] text-mist mt-0.5">بازی سرای رهرو • پیام‌های مستقیم مدیریت سالن</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-mist hover:text-paper text-xs px-2.5 py-1 rounded-lg bg-ink/80 border border-line/60 hover:bg-line/20 transition-colors"
          >
            ✕ بستن
          </button>
        </div>

        <div className="overflow-y-auto py-4 space-y-3 flex-1 pr-1 pl-1">
          {items.map((item) => {
            const style = typeConfig[item.type || "info"] || typeConfig.info;
            return (
              <div
                key={item.id}
                className={`panel p-4 border rounded-xl transition-all ${style.border} ${style.bg}`}
              >
                <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
                  <div className="flex items-center gap-2">
                    <span className="text-base">{style.icon}</span>
                    <h4 className="text-sm font-bold text-paper">{item.title}</h4>
                  </div>
                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded-md border ${style.badge}`}>
                    {style.label}
                  </span>
                </div>
                <p className="text-xs text-mist leading-relaxed font-medium whitespace-pre-wrap">
                  {item.content}
                </p>
                <div className="mt-3 pt-2.5 border-t border-line/40 flex items-center justify-between text-[10px] text-mist">
                  <span>{item.author || "مدیریت بازی سرای رهرو"}</span>
                  {item.createdAt && (
                    <span dir="ltr">{new Date(item.createdAt).toLocaleDateString("fa-IR")}</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div className="pt-3 border-t border-line/60 flex items-center justify-between text-[11px] text-mist">
          <span>مسجد امیرالمؤمنین (ع) دورشهر • بازی سرای رهرو</span>
          <button
            type="button"
            onClick={onClose}
            className="btn btn-primary text-xs py-1.5 px-4"
          >
            متوجه شدم
          </button>
        </div>
      </div>
    </div>
  );
}

function ChangePasswordModal({
  onClose,
  onSuccess,
}: {
  onClose: () => void;
  onSuccess: (msg: string) => void;
}): JSX.Element {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!currentPassword) {
      setError("لطفاً رمز عبور فعلی خود را وارد کنید.");
      return;
    }
    if (!newPassword || newPassword.length < 4) {
      setError("رمز عبور جدید باید حداقل ۴ رقم یا کاراکتر باشد.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("تکرار رمز عبور جدید با رمز جدید همخوانی ندارد.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await window.gamenet.changeUserPassword({
        currentPassword: currentPassword.trim(),
        newPassword: newPassword.trim(),
      });
      if (!res.ok) {
        setError(res.error || "خطا در تغییر رمز عبور.");
      } else {
        onSuccess(res.message || "رمز عبور با موفقیت به‌روزرسانی شد.");
        onClose();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا در برقراری ارتباط با سرور.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/80 p-4 animate-in fade-in duration-200">
      <div className="panel max-w-md w-full p-6 shadow-2xl border border-neon/30 relative">
        <div className="flex items-center justify-between pb-4 border-b border-line/60">
          <div className="flex items-center gap-2">
            <span className="text-xl">🔑</span>
            <h3 className="font-bold text-base text-paper">تغییر رمز عبور حساب کاربری</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-mist hover:text-paper text-sm p-1"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          {error && (
            <div className="p-3 rounded-xl border border-danger/40 bg-danger/10 text-danger text-xs leading-5">
              {error}
            </div>
          )}

          <div>
            <label className="block text-xs text-mist mb-1">رمز عبور فعلی (پیش‌فرض: شماره موبایل)</label>
            <input
              type="password"
              className="field text-sm font-mono"
              dir="ltr"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              placeholder="رمز فعلی یا شماره موبایل"
              autoFocus
            />
          </div>

          <div>
            <label className="block text-xs text-mist mb-1">رمز عبور جدید</label>
            <input
              type="password"
              className="field text-sm font-mono"
              dir="ltr"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="حداقل ۴ کاراکتر یا عدد"
            />
          </div>

          <div>
            <label className="block text-xs text-mist mb-1">تکرار رمز عبور جدید</label>
            <input
              type="password"
              className="field text-sm font-mono"
              dir="ltr"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="تکرار رمز جدید"
            />
          </div>

          <div className="flex items-center justify-end gap-2 pt-2 border-t border-line/60">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="btn btn-ghost text-xs py-2 px-4"
            >
              انصراف
            </button>
            <button
              type="submit"
              disabled={submitting || !newPassword}
              className="btn btn-solid text-xs py-2 px-5"
            >
              {submitting ? <Spinner className="h-4 w-4" /> : "ذخیره رمز جدید"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function QuickHardwareControls(): JSX.Element {
  const [volume, setVolume] = useState(75);
  const [mouseSpeed, setMouseSpeed] = useState(10);
  const [isMuted, setIsMuted] = useState(false);
  const [prevVolume, setPrevVolume] = useState(75);

  useEffect(() => {
    window.gamenet.getSystemSettings().then((settings) => {
      if (settings) {
        if (typeof settings.volume === "number") setVolume(settings.volume);
        if (typeof settings.mouseSpeed === "number") setMouseSpeed(settings.mouseSpeed);
      }
    }).catch(() => {});
  }, []);

  const handleVolumeChange = (newVal: number) => {
    setVolume(newVal);
    if (newVal > 0) setIsMuted(false);
    window.gamenet.setSystemVolume(newVal).catch(() => {});
  };

  const toggleMute = () => {
    if (isMuted) {
      setIsMuted(false);
      handleVolumeChange(prevVolume || 50);
    } else {
      setPrevVolume(volume);
      setIsMuted(true);
      handleVolumeChange(0);
    }
  };

  const handleMouseChange = (newVal: number) => {
    setMouseSpeed(newVal);
    window.gamenet.setMouseSpeed(newVal).catch(() => {});
  };

  return (
    <div className="rounded-2xl border border-line/70 bg-ink/50 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-bold text-paper flex items-center gap-1.5">
          <span>⚙️</span> تنظیمات سخت‌افزاری سیستم
        </h4>
        <span className="text-[10px] text-mist">تغییر بی‌درنگ در ویندوز (صدا و سنسور موس)</span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Volume Slider */}
        <div className="rounded-xl border border-line/50 bg-ink/60 p-3">
          <div className="flex items-center justify-between mb-1.5">
            <button
              type="button"
              onClick={toggleMute}
              className="text-xs text-mist hover:text-paper flex items-center gap-1"
              title={isMuted ? "وصل صدا" : "قطع صدا (Mute)"}
            >
              <span>{isMuted || volume === 0 ? "🔇" : volume < 50 ? "🔉" : "🔊"}</span>
              <span className="font-medium">صدای ویندوز</span>
            </button>
            <span className="font-mono text-xs font-bold text-neon">{isMuted ? "Mute" : `${volume}%`}</span>
          </div>
          <input
            type="range"
            min="0"
            max="100"
            step="2"
            value={isMuted ? 0 : volume}
            onChange={(e) => handleVolumeChange(Number(e.target.value))}
            className="w-full accent-neon cursor-pointer h-1.5 bg-line/60 rounded-lg"
          />
        </div>

        {/* Mouse Sensitivity Slider */}
        <div className="rounded-xl border border-line/50 bg-ink/60 p-3">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs text-mist flex items-center gap-1">
              <span>🖱️</span>
              <span className="font-medium">سنسور / سرعت موس</span>
            </span>
            <span className="font-mono text-xs font-bold text-neon">{mouseSpeed} / ۲۰</span>
          </div>
          <input
            type="range"
            min="1"
            max="20"
            step="1"
            value={mouseSpeed}
            onChange={(e) => handleMouseChange(Number(e.target.value))}
            className="w-full accent-neon cursor-pointer h-1.5 bg-line/60 rounded-lg"
          />
        </div>
      </div>
    </div>
  );
}

function UnlockedScreen({
  state,
  games,
  busy,
  onLock,
}: {
  state: PublicState;
  games: GameItem[];
  busy: boolean;
  onLock: () => void;
}): JSX.Element {
  const session = state.userSession;
  const [unlockedAt, setUnlockedAt] = useState(() => performance.now());
  const [activeGameId, setActiveGameId] = useState<string | null>(null);
  const [launchingId, setLaunchingId] = useState<string | null>(null);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [showAnnouncementsModal, setShowAnnouncementsModal] = useState(false);
  const [showChangePassword, setShowChangePassword] = useState(false);
  const [feedbackNotice, setFeedbackNotice] = useState<string | null>(null);

  useEffect(() => {
    setUnlockedAt(performance.now());
  }, [state.locked, session?.startedAt]);
  const now = useNow(!state.locked, true);
  const clockAnchor = useRef({ sessionId: session?.sessionId, syncedAt: session?.syncedAt, receivedAt: performance.now() });
  if (clockAnchor.current.sessionId !== session?.sessionId || clockAnchor.current.syncedAt !== session?.syncedAt) {
    clockAnchor.current = { sessionId: session?.sessionId, syncedAt: session?.syncedAt, receivedAt: performance.now() };
  }
  // The hub is the source of truth: local wall clock kept counting while the PC
  // slept or the session was paused, which produced multi-hour "ghost" timers.
  const hubElapsed = session?.elapsedSeconds;
  const elapsedSec =
    typeof hubElapsed === "number" && hubElapsed >= 0
      ? Math.max(0, Math.floor(hubElapsed + (session?.paused ? 0 : Math.max(0, now - clockAnchor.current.receivedAt) / 1000)))
      : Math.max(0, Math.floor((now - unlockedAt) / 1000));
  const elapsedFormatted = useMemo(
    () => duration(elapsedSec * 1000),
    [elapsedSec],
  );

  const couponHours = session?.couponHours || 0;
  const couponRate = session?.couponHourlyRate || 20000;
  const normalRate = session?.hourlyRate || 40000;
  const couponSec = couponHours * 3600;

  let currentCost = 0;
  if (couponHours > 0 && couponRate < normalRate) {
    if (elapsedSec <= couponSec) {
      currentCost = Math.ceil((elapsedSec * couponRate) / 3600);
    } else {
      currentCost = Math.ceil((couponSec * couponRate + (elapsedSec - couponSec) * normalRate) / 3600);
    }
  } else {
    currentCost = Math.ceil((elapsedSec * normalRate) / 3600);
  }
  const remainingWallet = session
    ? Math.max(
        0,
        (typeof session.remainingBalance === "number" ? session.remainingBalance : session.walletBalance - (session.serverCost || 0)) -
          Math.max(0, currentCost - (session.serverCost || 0)),
      )
    : 0;
  const totalAvailable = session ? remainingWallet + (session.creditLimit || 0) : 0;

  const handleLaunchGame = async (game: GameItem) => {
    setLaunchError(null);
    setLaunchingId(game.id);
    try {
      const res = await window.gamenet.launchGame({
        id: game.id,
        name: game.name,
        executable: game.executable,
        arguments: game.arguments,
        workingDir: game.workingDir,
      });
      if (res.ok) {
        setActiveGameId(game.id);
      } else {
        setLaunchError(res.error || "خطا در اجرای بازی روی این سیستم.");
      }
    } catch (err) {
      setLaunchError(err instanceof Error ? err.message : "خطا در اجرای بازی روی این سیستم.");
    } finally {
      setLaunchingId(null);
    }
  };

  const activeGames = games.filter((g) => g.enabled !== false);

  return (
    <section className="fade-up mx-auto w-full max-w-4xl space-y-6">
      <div className="panel relative overflow-hidden p-6 sm:p-10">
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-l from-transparent via-neon/70 to-transparent" />
        <div className="pointer-events-none absolute -left-20 -top-24 h-72 w-72 rounded-full pro-glow " />

        <div className="relative flex flex-col justify-between gap-6 md:flex-row md:items-start">
          <div className="min-w-0">
            <span className="chip chip-live">
              <span className="h-2 w-2 animate-pulse rounded-full bg-neon" />
              نشست بازی فعال است
            </span>
            <h1 className="mt-4 text-3xl font-bold sm:text-4xl text-paper">
              خوش آمدید، <span className="text-neon">{session?.customerName || state.deviceName || "گیمر عزیز"}</span>
            </h1>
            <p className="mt-2 text-sm text-mist">
              {session?.username ? `@${session.username} • ` : ""}
              {couponHours > 0 && elapsedSec < couponSec
                ? `تعرفه ویژه کوپن رهرو (${fa(couponRate.toLocaleString())} تومان/ساعت)`
                : `${session?.tariffName || "تعرفه بازی"} (${fa(normalRate.toLocaleString())} تومان/ساعت)`}
            </p>
          </div>

          <div className="shrink-0 rounded-2xl border border-neon/30 bg-neon/[0.08] px-7 py-5 text-center shadow-glow">
            <p className="text-[10px] uppercase tracking-[0.18em] text-mist">مدت زمان بازی</p>
            <p className="timer mt-2 text-3xl font-bold text-neon">{elapsedFormatted}</p>
            <p className="mt-1 text-[11px] text-mist font-medium">هزینه جاری: {fa(currentCost.toLocaleString())} ت</p>
          </div>
        </div>

        {/* Active coupon banner */}
        {couponHours > 0 && (
          <div className="mt-4 rounded-xl border border-neon/50 bg-neon/10 p-3.5 text-xs text-paper flex items-center justify-between gap-3 shadow-glow">
            <div className="flex items-center gap-2.5">
              <span className="text-xl">🎁</span>
              <div>
                <p className="font-bold text-neon flex items-center gap-2">
                  <span>تخفیف کوپن رهرو فعال است</span>
                  <span className="chip chip-live text-[10px] py-0 px-1.5">{fa(couponHours)} ساعت</span>
                </p>
                <p className="text-[11px] text-mist mt-0.5">
                  {elapsedSec < couponSec
                    ? `تا ${fa(Math.max(1, Math.ceil((couponSec - elapsedSec) / 60)))} دقیقه دیگر با تعرفه ویژه ${fa(couponRate.toLocaleString())} تومان در ساعت محاسبه می‌شوید.`
                    : "مدت زمان تخفیف کوپن به پایان رسید؛ ادامه زمان با تعرفه عادی محاسبه می‌شود."}
                </p>
              </div>
            </div>
            <span className="chip chip-live shrink-0 text-[10px]">
              {`${fa((elapsedSec < couponSec ? couponRate : normalRate).toLocaleString())} ت/ساعت`}
            </span>
          </div>
        )}

        {/* Low balance warning */}
        {session && totalAvailable <= 5000 && (
          <div className="mt-4 rounded-xl border border-amber/40 bg-amber/10 p-3 text-xs text-amber flex items-center gap-2">
            <span>⚠️</span>
            <span>اعتبار شما رو به پایان است ({fa(Math.max(0, totalAvailable).toLocaleString())} تومان). جهت تمدید به مسئول صندوق مراجعه فرمایید.</span>
          </div>
        )}

        {/* Success notification */}
        {feedbackNotice && (
          <div className="mt-4 rounded-xl border border-neon/40 bg-neon/10 p-3 text-xs text-neon flex items-center justify-between">
            <span className="flex items-center gap-2">
              <span>✓</span>
              <span>{feedbackNotice}</span>
            </span>
            <button type="button" onClick={() => setFeedbackNotice(null)} className="text-mist hover:text-paper text-xs">✕</button>
          </div>
        )}

        {/* Live Metrics */}
        <div className="relative mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-2xl border border-line/70 bg-ink/50 p-4">
            <p className="text-[10px] uppercase tracking-wider text-mist">دستگاه</p>
            <p className="mt-1 text-sm font-bold text-paper truncate">{state.deviceName || "PC-01"}</p>
          </div>
          <div className="rounded-2xl border border-line/70 bg-ink/50 p-4">
            <p className="text-[10px] uppercase tracking-wider text-mist">مانده کیف پول</p>
            <p className="mt-1 text-sm font-bold text-neon">{session ? `${fa(remainingWallet.toLocaleString())} ت` : "—"}</p>
          </div>
          <div className="rounded-2xl border border-line/70 bg-ink/50 p-4">
            <p className="text-[10px] uppercase tracking-wider text-mist">نرخ تعرفه</p>
            <p className="mt-1 text-sm font-bold text-paper">{fa(normalRate.toLocaleString())} ت/س</p>
          </div>
          <div className="rounded-2xl border border-line/70 bg-ink/50 p-4">
            <p className="text-[10px] uppercase tracking-wider text-mist">هاب سالن محلی</p>
            <p className="mt-1 text-sm font-bold text-mist truncate">{state.hubName || "سالن اصلی"}</p>
          </div>
        </div>

        {/* Quick Hardware Controls (Volume & Mouse Sensitivity) */}
        <div className="mt-6">
          <QuickHardwareControls />
        </div>

        {/* ======================================================== */}
        {/* Game Launcher Section */}
        {/* ======================================================== */}
        <div className="mt-8 border-t border-line/60 pt-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
            <div>
              <h2 className="text-lg font-bold text-paper flex items-center gap-2">
                <span>🎮</span> منوی بازی‌ها (لانچر کیوسک سالن)
              </h2>
              <p className="text-xs text-mist mt-0.5">روی بازی مورد نظر کلیک کنید تا اجرا و فعال شود</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setShowAnnouncementsModal(true)}
                className="btn btn-ghost text-xs py-1.5 px-3 border-neon/40 text-neon hover:bg-neon/10 flex items-center gap-1.5"
                title="مشاهده پیام‌ها و اطلاعیه‌های مدیریت سالن"
              >
                <span>📢</span> پیام‌های سالن
                {state.announcements && state.announcements.length > 0 && (
                  <span className="bg-neon text-ink text-[10px] font-extrabold px-1.5 py-0.2 rounded-full">
                    {fa(state.announcements.length)}
                  </span>
                )}
              </button>
              <button
                type="button"
                onClick={() => setShowChangePassword(true)}
                className="btn btn-ghost text-xs py-1.5 px-3 border-line/70 hover:border-neon flex items-center gap-1.5"
                title="تغییر رمز عبور حساب کاربری"
              >
                <span>🔑</span> تغییر رمز
              </button>
              {activeGameId && (
                <span className="chip border-neon/40 text-neon bg-neon/10">
                  <span className="h-2 w-2 rounded-full bg-neon animate-pulse" />
                  بازی در حال اجرا
                </span>
              )}
            </div>
          </div>

          {launchError && (
            <div role="alert" className="mb-4 rounded-xl border border-danger/40 bg-danger/10 p-3 text-xs text-danger flex items-center justify-between gap-2">
              <span>⚠️ {launchError}</span>
              <button type="button" onClick={() => setLaunchError(null)} className="text-mist hover:text-paper text-xs">✕</button>
            </div>
          )}

          {activeGames.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-line/60 bg-ink/40 p-6 text-center text-xs leading-6 text-mist">
              هیچ بازی فعالی برای این ایستگاه تنظیم نشده است.
              <br />
              از مسئول سالن بخواهید بازی‌های این سیستم را از پنل مدیریت فعال کند.
            </div>
          ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {activeGames.map((game) => {
              const isRunning = activeGameId === game.id;
              const isLaunching = launchingId === game.id;

              return (
                <div
                  key={game.id}
                  className={`rounded-2xl border p-4 transition-colors duration-150 flex flex-col justify-between ${game.color || "border-neon/30 bg-neon/[0.06]"} ${isRunning ? "ring-2 ring-neon" : "hover:scale-[1.02]"}`}
                >
                  <div className="flex items-start justify-between">
                    <span className="text-2xl">{game.icon}</span>
                    <span className="text-[10px] text-mist font-medium px-2 py-0.5 rounded-md bg-ink/60 border border-line/50">
                      {game.category}
                    </span>
                  </div>

                  <div className="mt-3">
                    <h3 className="text-sm font-bold text-paper">{game.name}</h3>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleLaunchGame(game)}
                    disabled={isLaunching || busy}
                    className={`mt-4 w-full text-xs py-2 rounded-xl font-bold flex items-center justify-center gap-1.5 transition-all ${
                      isRunning
                        ? "bg-neon text-ink hover:bg-neon/90"
                        : "bg-ink/70 hover:bg-ink text-paper border border-line/70"
                    }`}
                  >
                    {isLaunching ? (
                      <Spinner className="h-3.5 w-3.5" />
                    ) : isRunning ? (
                      <span>در حال اجرا • اجرای مجدد</span>
                    ) : (
                      <span>شروع بازی</span>
                    )}
                  </button>
                </div>
              );
            })}
          </div>
          )}
        </div>

        <div className="relative mt-8 flex flex-wrap items-center justify-between gap-4 border-t border-line/60 pt-6">
          <p className="flex items-center gap-2 text-xs text-mist">
            <ShieldIcon className="h-4 w-4 text-neon" />
            کیوسک مد فعال است؛ با خروج، تمامی برنامه‌ها بسته شده و سیستم قفل می‌شود.
          </p>
          <button
            type="button"
            className="btn btn-ghost hover:bg-danger/20 hover:text-danger hover:border-danger/40 transition-colors"
            onClick={onLock}
            disabled={busy}
          >
            {busy ? <Spinner className="h-4 w-4" /> : <LockIcon className="h-4 w-4" />}
            پایان بازی و خروج از حساب
          </button>
        </div>
      </div>

      {showAnnouncementsModal && (
        <AnnouncementsModal
          announcements={state.announcements}
          onClose={() => setShowAnnouncementsModal(false)}
        />
      )}
      {showChangePassword && (
        <ChangePasswordModal
          onClose={() => setShowChangePassword(false)}
          onSuccess={(msg) => {
            setFeedbackNotice(msg);
            setTimeout(() => setFeedbackNotice(null), 5000);
          }}
        />
      )}
    </section>
  );
}

function Clock({ className = "" }: { className?: string }): JSX.Element {
  const now = useNow(true);
  const text = new Intl.DateTimeFormat("fa-IR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(now);
  return (
    <span className={className} dir="ltr">
      {text}
    </span>
  );
}

function ClientTaskbar({
  onQuickLogout,
  onPower,
}: {
  onQuickLogout: () => void;
  onPower: (action: PowerAction) => void;
}): JSX.Element {
  const [apps, setApps] = useState<RunningAppWindow[]>([]);
  const [selectedAppHwnd, setSelectedAppHwnd] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);

  const refreshApps = () => {
    window.gamenet.getRunningApps().then((list) => {
      if (Array.isArray(list)) {
        setApps(list);
      }
    }).catch(() => {});
  };

  useEffect(() => {
    refreshApps();
    const interval = window.setInterval(refreshApps, 2500);
    const unsub = window.gamenet.onAppsUpdated ? window.gamenet.onAppsUpdated(() => refreshApps()) : undefined;
    return () => {
      window.clearInterval(interval);
      if (unsub) unsub();
    };
  }, []);

  const handleFocus = async (hwnd: string) => {
    setBusyAction(hwnd);
    try {
      await window.gamenet.focusApp(hwnd);
      setSelectedAppHwnd(null);
      refreshApps();
    } finally {
      setBusyAction(null);
    }
  };

  const handleMinimize = async (hwnd: string) => {
    setBusyAction(hwnd);
    try {
      await window.gamenet.minimizeApp(hwnd);
      setSelectedAppHwnd(null);
      refreshApps();
    } finally {
      setBusyAction(null);
    }
  };

  const handleClose = async (hwnd: string, pid?: number) => {
    setBusyAction(hwnd);
    try {
      await window.gamenet.closeApp(hwnd, pid);
      setSelectedAppHwnd(null);
      setTimeout(refreshApps, 500);
    } finally {
      setBusyAction(null);
    }
  };

  const handleSwitchNext = async () => {
    await window.gamenet.switchNextApp();
    refreshApps();
  };

  const activeApp = apps.find((a) => a.id === selectedAppHwnd);

  return (
    <div className="fixed bottom-0 inset-x-0 z-40 h-14 bg-[#0a0f18]/95 border-t border-line/80 px-4 flex items-center justify-between select-none shadow-[0_-4px_24px_rgba(0,0,0,0.5)]">
      {/* Popover Action Menu for selected app */}
      {activeApp && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center pb-16 bg-black/40"
          onClick={() => setSelectedAppHwnd(null)}
        >
          <div
            className="panel max-w-sm w-full p-4 mx-4 shadow-2xl border-neon/50 bg-[#0d1522] animate-in slide-in-from-bottom-4 duration-150 space-y-3"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between pb-2 border-b border-line/60">
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-xl">{activeApp.icon}</span>
                <div className="min-w-0">
                  <h4 className="text-xs font-bold text-paper truncate">{activeApp.name}</h4>
                  <p className="text-[10px] text-mist font-mono truncate">{activeApp.processName} • PID: {activeApp.pid}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setSelectedAppHwnd(null)}
                className="w-6 h-6 rounded-md grid place-items-center bg-ink/60 text-mist hover:text-paper text-xs"
              >
                ✕
              </button>
            </div>

            <div className="grid grid-cols-3 gap-2">
              <button
                type="button"
                disabled={Boolean(busyAction) || !activeApp.hwnd}
                onClick={() => handleFocus(activeApp.hwnd)}
                className="flex flex-col items-center justify-center p-2.5 rounded-xl border border-emerald-500/40 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 text-xs font-bold gap-1 transition-all"
                title="نمایش و آوردن بازی به جلو"
              >
                <ExternalIcon className="h-4 w-4" />
                <span>باز کردن</span>
              </button>

              <button
                type="button"
                disabled={Boolean(busyAction) || !activeApp.hwnd}
                onClick={() => handleMinimize(activeApp.hwnd)}
                className="flex flex-col items-center justify-center p-2.5 rounded-xl border border-amber/40 bg-amber/10 hover:bg-amber/20 text-amber text-xs font-bold gap-1 transition-all"
                title="کوچک کردن پنجره به نوار"
              >
                <MinimizeIcon className="h-4 w-4" />
                <span>مینیمایز</span>
              </button>

              <button
                type="button"
                disabled={Boolean(busyAction)}
                onClick={() => handleClose(activeApp.hwnd, activeApp.pid)}
                className="flex flex-col items-center justify-center p-2.5 rounded-xl border border-danger/40 bg-danger/10 hover:bg-danger/20 text-danger text-xs font-bold gap-1 transition-all"
                title="بستن پنجره و خروج از برنامه"
              >
                <CloseIcon className="h-4 w-4" />
                <span>بستن</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Right: Start Brand & Alt-Tab Switcher */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setSelectedAppHwnd(null)}
          className="flex items-center gap-2 px-3 py-1.5 rounded-xl border border-neon/30 bg-neon/10 hover:bg-neon/20 text-neon text-xs font-bold shadow-glow transition-all"
          title="بازی سرای رهرو - بازگشت به منوی کیوسک"
        >
          <span>🎮</span>
          <span className="hidden sm:inline">بازی سرای رهرو</span>
        </button>

        <button
          type="button"
          onClick={handleSwitchNext}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-line/70 bg-ink/60 hover:bg-neon/10 hover:border-neon text-xs font-medium text-paper transition-all"
          title="سوییچ بین بازی‌ها و برنامه‌ها (کلید Alt + Tab)"
        >
          <span className="text-neon font-bold">⇋</span>
          <span className="hidden md:inline">سوییچ پنجره (Alt+Tab)</span>
        </button>
      </div>

      {/* Center: Running Applications Deck */}
      <div className="flex-1 flex items-center justify-center px-4 overflow-x-auto gap-2 max-w-2xl no-scrollbar">
        {apps.length === 0 ? (
          <span className="text-[11px] text-mist flex items-center gap-1.5">
            <span className="text-xs">🕹️</span> هیچ بازی یا برنامه‌ای در حال اجرا نیست
          </span>
        ) : (
          apps.map((app) => {
            const isSelected = selectedAppHwnd === app.id;
            return (
              <button
                key={app.id}
                type="button"
                onClick={() => setSelectedAppHwnd(isSelected ? null : app.id)}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-xl border text-xs font-medium transition-all max-w-[200px] shrink-0 ${
                  isSelected
                    ? "border-neon bg-neon/15 text-neon shadow-glow"
                    : app.isForeground
                    ? "border-emerald-500/50 bg-emerald-500/10 text-paper"
                    : "border-line/60 bg-ink/50 hover:bg-ink/90 text-mist hover:text-paper"
                }`}
                title={`کلیک برای: باز کردن، مینیمایز یا بستن ${app.name}`}
              >
                <span>{app.icon}</span>
                <span className="truncate">{app.name}</span>
                <span
                  className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                    app.isForeground ? "bg-emerald-400 animate-pulse" : app.isMinimized ? "bg-amber" : "bg-neon/60"
                  }`}
                />
              </button>
            );
          })
        )}
      </div>

      {/* Left: Alt+F5 Quick Logout & Digital Clock */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onPower("restart")}
          className="flex h-9 w-9 items-center justify-center rounded-xl border border-line/70 bg-ink/60 text-sm text-paper transition-colors hover:border-amber/50 hover:text-amber"
          title="راه‌اندازی مجدد سیستم"
          aria-label="راه‌اندازی مجدد سیستم"
        >
          <RestartIcon className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => onPower("shutdown")}
          className="flex h-9 w-9 items-center justify-center rounded-xl border border-line/70 bg-ink/60 text-sm text-danger transition-colors hover:border-danger/50 hover:bg-danger/10"
          title="خاموش کردن سیستم"
          aria-label="خاموش کردن سیستم"
        >
          <PowerIcon className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={onQuickLogout}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-amber/40 bg-amber/10 hover:bg-amber/20 text-xs font-bold text-amber shadow-sm transition-colors"
          title="خروج از حساب کاربری بدون بستن بازی‌ها (Alt + F5)"
        >
          <LockIcon className="h-4 w-4" />
          <span className="hidden lg:inline">خروج موقت (Alt+F5)</span>
        </button>

        <span className="font-mono text-xs font-semibold text-paper/80 hidden sm:inline" dir="ltr">
          <Clock />
        </span>
      </div>
    </div>
  );
}

function Toasts({
  notices,
  dismiss,
}: {
  notices: CommandNotice[];
  dismiss: (notice: CommandNotice) => void;
}): JSX.Element {
  return (
    <div className="pointer-events-none fixed bottom-20 left-6 z-50 flex w-[min(92vw,360px)] flex-col gap-2" aria-live="polite">
      {notices.slice(-3).map((notice) => (
        <button
          key={`${notice.at}-${notice.commandId}-${notice.message}`}
          type="button"
          onClick={() => dismiss(notice)}
          className={`toast pointer-events-auto flex items-start gap-3 rounded-2xl border px-4 py-3 text-right ${
            notice.outcome === "ok"
              ? "border-neon/25 bg-panel/95"
              : "border-danger/30 bg-panel/95"
          }`}
        >
          <span
            className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg text-xs ${
              notice.outcome === "ok" ? "bg-neon/10 text-neon" : "bg-danger/10 text-danger"
            }`}
          >
            {notice.outcome === "ok" ? "✓" : "!"}
          </span>
          <span className="min-w-0">
            <span className="block text-xs font-medium leading-5 text-paper">{notice.message}</span>
            <span className="mt-0.5 block font-mono text-[10px] text-mist" dir="ltr">
              {notice.commandType}
            </span>
          </span>
        </button>
      ))}
    </div>
  );
}

function AppInner(): JSX.Element {
  const [state, setState] = useState<PublicState | null>(null);
  const [notices, setNotices] = useState<CommandNotice[]>([]);
  const [busy, setBusy] = useState(false);
  const [showAdminEscape, setShowAdminEscape] = useState(false);
  const [games, setGames] = useState<GameItem[]>([]);
  const [updateProgress, setUpdateProgress] = useState<{ percent: number; message: string } | null>(null);
  const [powerAction, setPowerAction] = useState<PowerAction | null>(null);
  const [powerBusy, setPowerBusy] = useState(false);

  const confirmPower = async (): Promise<void> => {
    if (!powerAction) return;
    setPowerBusy(true);
    try {
      const res = await window.gamenet.systemPower(powerAction);
      if (!res.ok) {
        setNotices((current) => [
          ...current.slice(-4),
          {
            commandId: "",
            commandType: "system",
            outcome: "error",
            message: res.error || "اجرای دستور سیستم ناموفق بود",
            at: new Date().toISOString(),
          },
        ]);
      }
    } catch (err) {
      setNotices((current) => [
        ...current.slice(-4),
        {
          commandId: "",
          commandType: "system",
          outcome: "error",
          message: err instanceof Error ? err.message : "خطا در اجرای دستور سیستم",
          at: new Date().toISOString(),
        },
      ]);
    } finally {
      setPowerBusy(false);
      setPowerAction(null);
    }
  };

  useEffect(() => {
    window.gamenet.getGames().then((loaded) => {
      if (Array.isArray(loaded)) setGames(loaded);
    }).catch(() => {});
    const unsubscribeGames = window.gamenet.onGamesUpdated
      ? window.gamenet.onGamesUpdated((updated) => {
          if (Array.isArray(updated)) setGames(updated);
        })
      : undefined;
    return () => {
      if (unsubscribeGames) unsubscribeGames();
    };
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setShowAdminEscape((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    const unsubscribeTrigger = window.gamenet.onTriggerAdminEscape ? window.gamenet.onTriggerAdminEscape(() => {
      setShowAdminEscape((prev) => !prev);
    }) : undefined;
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      if (unsubscribeTrigger) unsubscribeTrigger();
    };
  }, []);

  useEffect(() => {
    let alive = true;
    window.gamenet
      .snapshot()
      .then((snapshot) => {
        if (alive) setState(snapshot);
      })
      .catch(() => {
        if (alive) setState(null);
      });
    const unsubscribeState = window.gamenet.onState((next) => setState(next));
    const unsubscribeCommand = window.gamenet.onCommand((notice) => {
      setNotices((current) => [...current.slice(-4), notice]);
      window.setTimeout(() => {
        setNotices((current) => current.filter((item) => item !== notice));
      }, 6500);
    });
    const unsubscribeUpdate = window.gamenet.onUpdateProgress?.((progress) =>
      setUpdateProgress(progress),
    );
    return () => {
      alive = false;
      unsubscribeState();
      unsubscribeCommand();
      if (unsubscribeUpdate) unsubscribeUpdate();
    };
  }, []);

  async function act(action: "preview" | "lock" | "unpair" | "userLogout" | "userLogoutQuick"): Promise<void> {
    if (busy) return;
    setBusy(true);
    try {
      if (action === "preview") {
        setState(await window.gamenet.preview(true));
      } else if (action === "userLogout") {
        const res = await window.gamenet.userLogout();
        setState(res.state);
      } else if (action === "userLogoutQuick") {
        const res = await window.gamenet.userLogoutQuick();
        setState(res.state);
      } else if (action === "lock") {
        setState(await window.gamenet.lock());
      } else {
        const result = await window.gamenet.unpair();
        setState(result.state);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative flex h-screen flex-col overflow-hidden bg-ink text-paper">
      <div className="backdrop" aria-hidden="true" />

      {updateProgress ? (
        <div className="fixed inset-x-0 top-0 z-50 border-b border-neon/30 bg-ink/95 px-4 py-1.5 text-center text-[11px] text-neon">
          {updateProgress.message} ({fa(updateProgress.percent)}٪)
        </div>
      ) : null}

      <header className="relative z-10 mx-auto flex w-full max-w-6xl shrink-0 items-center justify-between gap-4 px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl border border-neon/25 bg-neon/10 text-neon shadow-glow">
            <GamepadMark className="h-5 w-5" />
          </div>
          <div className="leading-tight">
            <p className="text-sm font-bold tracking-tight">بازی سرای رهرو</p>
            <p className="text-[10px] text-mist">
              مسجد امیرالمؤمنین (ع) • {state?.paired ? state.deviceName || state.hubName || "رایانه بازی" : "ثبت رایانه بازی"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {state ? <StatusPill phase={state.phase} /> : null}
          <span className="hidden font-mono text-xs text-mist sm:inline" dir="ltr">
            <Clock />
          </span>
        </div>
      </header>

      <main className={`relative z-10 min-h-0 flex-1 overflow-y-auto${state && !state.locked ? " pb-16" : ""}`}>
        <div className="flex min-h-full w-full justify-center px-6 py-4">
          <div className="my-auto w-full">
            {!state ? (
              <div className="flex flex-col items-center gap-4 text-mist">
                <Spinner className="h-7 w-7 text-neon" />
                <p className="text-xs">در حال خواندن وضعیت دستگاه…</p>
              </div>
            ) : !state.paired ? (
              <PairingScreen
                state={state}
                onPaired={setState}
              />
            ) : state.locked ? (
              <LockedScreen state={state} busy={busy} onPreview={() => void act("preview")} onPower={setPowerAction} />
            ) : (
              <UnlockedScreen
                state={state}
                games={games}
                busy={busy}
                onLock={() => void act("userLogout")}
              />
            )}
          </div>
        </div>
      </main>

      <footer className="relative z-10 mx-auto flex w-full max-w-6xl shrink-0 flex-wrap items-center justify-between gap-2 border-t border-line/50 px-6 py-3 text-[10px] text-mist">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="font-mono" dir="ltr">
            {state?.fingerprintShort ? `cert ${state.fingerprintShort}` : "cert —"}
          </span>
          <span className="font-mono" dir="ltr">
            v{state?.appVersion || "0.1.0"}
          </span>
          <span>{state?.platform || ""}</span>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            className="text-mist hover:text-neon flex items-center gap-1 border border-line/50 rounded px-2 py-0.5"
            onClick={() => setShowAdminEscape(true)}
            title="خروج از کیوسک و مدیریت سیستم با فشردن Esc"
          >
            <span>🛡️</span>
            <span>مدیریت ادمین (Esc)</span>
          </button>
          {state?.canUnpair && state.paired ? (
            <button
              type="button"
              className="text-mist underline decoration-line underline-offset-4 hover:text-danger"
              onClick={() => {
                if (window.confirm("اتصال این دستگاه حذف شود؟")) void act("unpair");
              }}
            >
              حذف اتصال (توسعه)
            </button>
          ) : null}
          <span>بدون اینترنت هم به هاب محلی متصل است</span>
        </div>
      </footer>

      {state && !state.locked && (
        <ClientTaskbar
          onQuickLogout={() => void act("userLogoutQuick")}
          onPower={setPowerAction}
        />
      )}

      <AdminEscapeModal
        isOpen={showAdminEscape}
        state={state}
        onStateChange={(next) => setState(next)}
        onClose={() => setShowAdminEscape(false)}
      />

      <PowerConfirmModal
        action={powerAction}
        busy={powerBusy}
        onCancel={() => setPowerAction(null)}
        onConfirm={() => void confirmPower()}
      />

      <Toasts
        notices={notices}
        dismiss={(notice) => setNotices((current) => current.filter((item) => item !== notice))}
      />
    </div>
  );
}

export default function App(): JSX.Element {
  return (
    <ErrorBoundary>
      <AppInner />
    </ErrorBoundary>
  );
}
