import { useEffect, useMemo, useState } from "react";
import type {
  CommandNotice,
  ConnectionPhase,
  PublicState,
} from "../shared/ipc";

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

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
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

function UnlockIcon({ className = "" }: { className?: string }): JSX.Element {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className={className} aria-hidden="true">
      <rect x="4.5" y="10" width="15" height="10" rx="2.5" />
      <path d="M8 10V7.5a4 4 0 0 1 7.5-2M12 14v2.5" strokeLinecap="round" />
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
  initialName,
  lastError,
  onPaired,
}: {
  initialName: string;
  lastError: string;
  onPaired: (state: PublicState) => void;
}): JSX.Element {
  const [pairing, setPairing] = useState("");
  const [code, setCode] = useState("");
  const [name, setName] = useState(initialName);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(lastError);

  useEffect(() => {
    if (lastError) setError(lastError);
  }, [lastError]);

  async function submit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (busy) return;
    setError("");
    if (!pairing.includes("#")) {
      setError("رشته اتصال باید شامل # و اثر انگشت گواهی باشد");
      return;
    }
    if (code.trim().length < 4) {
      setError("کد ثبت دستگاه را کامل وارد کنید");
      return;
    }
    if (!name.trim()) {
      setError("نام رایانه را وارد کنید");
      return;
    }
    setBusy(true);
    try {
      const result = await window.gamenet.pair({ pairing, code, name });
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
    <section className="fade-up mx-auto grid w-full max-w-5xl gap-5 lg:grid-cols-[1.05fr_1fr]">
      <aside className="panel relative flex flex-col justify-between overflow-hidden p-8">
        <div className="pointer-events-none absolute -left-24 -top-24 h-64 w-64 rounded-full bg-neon/10 blur-3xl" />
        <div className="relative">
          <span className="chip">
            <ShieldIcon className="h-3.5 w-3.5" />
            اتصال امن به سالن
          </span>
          <h1 className="mt-6 text-3xl font-bold leading-snug text-paper">
            این رایانه را به
            <span className="text-neon"> هاب سالن </span>
            وصل کنید
          </h1>
          <p className="mt-3 max-w-md text-sm leading-7 text-mist">
            پس از ثبت، رایانه فقط از طریق هاب مدیریت می‌شود. فرمان‌های قفل و باز
            کردن از داشبورد ابری به هاب و سپس به همین دستگاه می‌رسند.
          </p>
        </div>

        <ol className="relative mt-8 space-y-4 text-sm">
          {[
            "رشته اتصال و اثر انگشت گواهی را از داشبورد هاب بردارید.",
            "یک کد ثبت یک‌بارمصرف در بخش دستگاه‌ها بسازید.",
            "نام رایانه را وارد کنید و اتصال را تأیید کنید.",
          ].map((step, index) => (
            <li key={step} className="flex items-start gap-3">
              <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full border border-neon/30 bg-neon/10 text-[11px] font-bold text-neon">
                {fa(index + 1)}
              </span>
              <span className="leading-6 text-mist">{step}</span>
            </li>
          ))}
        </ol>

        <div className="relative mt-8 flex items-start gap-3 rounded-2xl border border-line/80 bg-ink/50 p-4 text-xs leading-6 text-mist">
          <ShieldIcon className="mt-0.5 h-4 w-4 shrink-0 text-neon" />
          <p>
            گواهی هاب با اثر انگشت SHA-256 سنجاق می‌شود؛ اگر گواهی عوض شود،
            اتصال پیش از ارسال کلید دستگاه متوقف می‌شود.
          </p>
        </div>
      </aside>

      <form onSubmit={submit} className="panel flex flex-col p-8" noValidate>
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-mist">ثبت دستگاه</p>
          <h2 className="mt-2 text-2xl font-bold">مشخصات اتصال</h2>
        </div>

        <div className="mt-7 space-y-5">
          <Field id="pairing" label="رشته اتصال هاب" hint="host:port#fingerprint">
            <input
              id="pairing"
              className="field font-mono text-[13px]"
              dir="ltr"
              autoComplete="off"
              spellCheck={false}
              placeholder="192.168.1.20:9443#A1B2C3…"
              value={pairing}
              onChange={(event) => setPairing(event.target.value)}
              autoFocus
              disabled={busy}
            />
          </Field>

          <div className="grid gap-5 sm:grid-cols-[0.8fr_1.2fr]">
            <Field id="code" label="کد ثبت" hint="یک‌بارمصرف">
              <input
                id="code"
                className="field text-center font-mono text-base tracking-[0.25em]"
                dir="ltr"
                autoComplete="off"
                spellCheck={false}
                placeholder="A1B2C3D4"
                value={code}
                onChange={(event) => setCode(event.target.value.toUpperCase())}
                disabled={busy}
                maxLength={64}
              />
            </Field>
            <Field id="device-name" label="نام رایانه">
              <input
                id="device-name"
                className="field"
                value={name}
                onChange={(event) => setName(event.target.value)}
                disabled={busy}
                maxLength={80}
              />
            </Field>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-2 gap-2">
          <div className="rounded-xl border border-line/70 bg-ink/40 px-3 py-2.5">
            <p className="text-[9px] uppercase tracking-wider text-mist">کانال</p>
            <p className="mt-1 text-[11px] font-medium text-paper">WSS/TLS با سنجاق گواهی</p>
          </div>
          <div className="rounded-xl border border-line/70 bg-ink/40 px-3 py-2.5">
            <p className="text-[9px] uppercase tracking-wider text-mist">کلید دستگاه</p>
            <p className="mt-1 text-[11px] font-medium text-paper">DPAPI در ویندوز</p>
          </div>
        </div>

        {error ? (
          <div role="alert" aria-live="polite" className="mt-5 rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-xs leading-6 text-danger">
            {error}
          </div>
        ) : null}

        <div className="mt-auto pt-7">
          <button type="submit" className="btn btn-primary w-full" disabled={busy}>
            {busy ? <Spinner className="h-4 w-4" /> : <WifiIcon className="h-4 w-4" />}
            {busy ? "در حال اتصال…" : "اتصال و ثبت رایانه"}
          </button>
          <p className="mt-4 text-center text-[11px] leading-5 text-mist">
            این دستگاه بدون اینترنت هم به هاب محلی وصل می‌شود.
          </p>
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

function InfoChip({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <div className="rounded-2xl border border-line/70 bg-ink/40 px-4 py-3">
      <p className="text-[10px] uppercase tracking-wider text-mist">{label}</p>
      <p className="mt-1 truncate text-xs font-medium text-paper">{value}</p>
    </div>
  );
}

function LockedScreen({
  state,
  busy,
  onPreview,
}: {
  state: PublicState;
  busy: boolean;
  onPreview: () => void;
}): JSX.Element {
  const ready = state.phase === "connected";
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [loginError, setLoginError] = useState("");

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
          <div className="pointer-events-none absolute -left-20 -top-20 h-64 w-64 rounded-full bg-neon/5 blur-3xl" />

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
              <Field id="login-username" label="نام کاربری یا شماره همراه">
                <input
                  id="login-username"
                  className="field text-sm"
                  dir="ltr"
                  autoComplete="username"
                  placeholder="ali یا 0912..."
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  disabled={!ready || submitting}
                  autoFocus
                />
              </Field>

              <Field id="login-password" label="رمز عبور">
                <input
                  id="login-password"
                  type="password"
                  className="field text-sm font-mono"
                  dir="ltr"
                  autoComplete="current-password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={!ready || submitting}
                />
              </Field>
            </div>

            {loginError ? (
              <div role="alert" className="mt-4 rounded-xl border border-danger/30 bg-danger/10 p-3 text-xs leading-5 text-danger">
                {loginError}
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
    </section>
  );
}

interface GameItem {
  id: string;
  name: string;
  category: string;
  icon: string;
  executable?: string;
  color: string;
}

const GAMES_LIST: GameItem[] = [
  { id: "cs2", name: "Counter-Strike 2", category: "شوتر رقابتی", icon: "🎯", executable: "cs2.exe", color: "border-amber/30 bg-amber/[0.06]" },
  { id: "dota2", name: "Dota 2", category: "استراتژی تیمی", icon: "⚔️", executable: "dota2.exe", color: "border-danger/30 bg-danger/[0.06]" },
  { id: "fc24", name: "EA SPORTS FC 24", category: "فوتبال و ورزشی", icon: "⚽", executable: "fc24.exe", color: "border-neon/30 bg-neon/[0.06]" },
  { id: "gta5", name: "Grand Theft Auto V", category: "جهان‌باز و اکشن", icon: "🚗", executable: "gta5.exe", color: "border-sky-500/30 bg-sky-500/[0.06]" },
  { id: "warzone", name: "Call of Duty: Warzone", category: "بتل رویال", icon: "🪖", executable: "warzone.exe", color: "border-purple-500/30 bg-purple-500/[0.06]" },
  { id: "nfs", name: "Need for Speed", category: "اتومبیل‌رانی", icon: "🏎️", executable: "nfs.exe", color: "border-orange-500/30 bg-orange-500/[0.06]" },
];

function UnlockedScreen({
  state,
  busy,
  onLock,
}: {
  state: PublicState;
  busy: boolean;
  onLock: () => void;
}): JSX.Element {
  const session = state.userSession;
  const [unlockedAt, setUnlockedAt] = useState(() => Date.now());
  const [activeGameId, setActiveGameId] = useState<string | null>(null);
  const [launchingId, setLaunchingId] = useState<string | null>(null);

  useEffect(() => {
    setUnlockedAt(Date.now());
  }, [state.locked]);
  const now = useNow(!state.locked);
  const elapsedSec = Math.max(0, Math.floor((now - unlockedAt) / 1000));
  const elapsedFormatted = useMemo(() => duration(now - unlockedAt), [now, unlockedAt]);

  const hourlyRate = session?.hourlyRate || 40000;
  const currentCost = Math.ceil((elapsedSec * hourlyRate) / 3600);
  const remainingWallet = session ? Math.max(0, session.walletBalance - currentCost) : 0;

  const handleLaunchGame = async (game: GameItem) => {
    setLaunchingId(game.id);
    try {
      const res = await window.gamenet.launchGame({
        id: game.id,
        name: game.name,
        executable: game.executable,
      });
      if (res.ok) {
        setActiveGameId(game.id);
      }
    } catch {
      // Ignored
    } finally {
      setLaunchingId(null);
    }
  };

  return (
    <section className="fade-up mx-auto w-full max-w-4xl space-y-6">
      <div className="panel relative overflow-hidden p-6 sm:p-10">
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-l from-transparent via-neon/70 to-transparent" />
        <div className="pointer-events-none absolute -left-20 -top-24 h-72 w-72 rounded-full bg-neon/10 blur-3xl" />

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
              {session?.username ? `@${session.username} • ` : ""}{session?.tariffName || "تعرفه بازی"} ({fa(hourlyRate.toLocaleString())} تومان/ساعت)
            </p>
          </div>

          <div className="shrink-0 rounded-2xl border border-neon/30 bg-neon/[0.08] px-7 py-5 text-center shadow-glow">
            <p className="text-[10px] uppercase tracking-[0.18em] text-mist">مدت زمان بازی</p>
            <p className="timer mt-2 text-3xl font-bold text-neon">{elapsedFormatted}</p>
            <p className="mt-1 text-[11px] text-mist font-medium">هزینه جاری: {fa(currentCost.toLocaleString())} ت</p>
          </div>
        </div>

        {/* Low balance warning */}
        {remainingWallet <= 5000 && (
          <div className="mt-4 rounded-xl border border-amber/40 bg-amber/10 p-3 text-xs text-amber flex items-center gap-2">
            <span>⚠️</span>
            <span>اعتبار شما رو به پایان است ({fa(remainingWallet.toLocaleString())} تومان). جهت تمدید به مسئول صندوق مراجعه فرمایید.</span>
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
            <p className="mt-1 text-sm font-bold text-paper">{fa(hourlyRate.toLocaleString())} ت/س</p>
          </div>
          <div className="rounded-2xl border border-line/70 bg-ink/50 p-4">
            <p className="text-[10px] uppercase tracking-wider text-mist">هاب سالن محلی</p>
            <p className="mt-1 text-sm font-bold text-mist truncate">{state.hubName || "سالن اصلی"}</p>
          </div>
        </div>

        {/* ======================================================== */}
        {/* Game Launcher Section */}
        {/* ======================================================== */}
        <div className="mt-8 border-t border-line/60 pt-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-lg font-bold text-paper flex items-center gap-2">
                <span>🎮</span> منوی بازی‌ها (لانچر کیوسک سالن)
              </h2>
              <p className="text-xs text-mist mt-0.5">روی بازی مورد نظر کلیک کنید تا اجرا و فعال شود</p>
            </div>
            {activeGameId && (
              <span className="chip border-neon/40 text-neon bg-neon/10">
                <span className="h-2 w-2 rounded-full bg-neon animate-pulse" />
                یک بازی در حال اجرا است
              </span>
            )}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {GAMES_LIST.map((game) => {
              const isRunning = activeGameId === game.id;
              const isLaunching = launchingId === game.id;

              return (
                <div
                  key={game.id}
                  className={`rounded-2xl border p-4 transition-all duration-150 flex flex-col justify-between ${game.color} ${isRunning ? "ring-2 ring-neon" : "hover:scale-[1.02]"}`}
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
    </section>
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
    <div className="pointer-events-none fixed bottom-6 left-6 z-30 flex w-[min(92vw,360px)] flex-col gap-2" aria-live="polite">
      {notices.slice(-3).map((notice) => (
        <button
          key={`${notice.at}-${notice.commandId}-${notice.message}`}
          type="button"
          onClick={() => dismiss(notice)}
          className={`toast pointer-events-auto flex items-start gap-3 rounded-2xl border px-4 py-3 text-right backdrop-blur ${
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

export default function App(): JSX.Element {
  const [state, setState] = useState<PublicState | null>(null);
  const [notices, setNotices] = useState<CommandNotice[]>([]);
  const [busy, setBusy] = useState(false);
  const now = useNow(true);

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
    return () => {
      alive = false;
      unsubscribeState();
      unsubscribeCommand();
    };
  }, []);

  async function act(action: "preview" | "lock" | "unpair" | "userLogout"): Promise<void> {
    if (busy) return;
    setBusy(true);
    try {
      if (action === "preview") {
        setState(await window.gamenet.preview(true));
      } else if (action === "userLogout") {
        const res = await window.gamenet.userLogout();
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

  const clock = new Intl.DateTimeFormat("fa-IR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(now);

  return (
    <div className="relative flex h-screen flex-col overflow-hidden bg-ink text-paper">
      <div className="backdrop" aria-hidden="true" />

      <header className="relative z-10 mx-auto flex w-full max-w-6xl shrink-0 items-center justify-between gap-4 px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl border border-neon/25 bg-neon/10 text-neon shadow-glow">
            <GamepadMark className="h-5 w-5" />
          </div>
          <div className="leading-tight">
            <p className="text-sm font-bold tracking-tight">GameNet</p>
            <p className="text-[10px] text-mist">
              {state?.paired ? state.hubName || "رایانه بازی" : "ثبت رایانه بازی"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {state ? <StatusPill phase={state.phase} /> : null}
          <span className="hidden font-mono text-xs text-mist sm:inline" dir="ltr">
            {clock}
          </span>
        </div>
      </header>

      <main className="relative z-10 min-h-0 flex-1 overflow-y-auto">
        <div className="flex min-h-full w-full justify-center px-6 py-4">
          <div className="my-auto w-full">
            {!state ? (
              <div className="flex flex-col items-center gap-4 text-mist">
                <Spinner className="h-7 w-7 text-neon" />
                <p className="text-xs">در حال خواندن وضعیت دستگاه…</p>
              </div>
            ) : !state.paired ? (
              <PairingScreen
                initialName={state.suggestedName}
                lastError={state.lastError}
                onPaired={setState}
              />
            ) : state.locked ? (
              <LockedScreen state={state} busy={busy} onPreview={() => void act("preview")} />
            ) : (
              <UnlockedScreen state={state} busy={busy} onLock={() => void act("userLogout")} />
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

      <Toasts
        notices={notices}
        dismiss={(notice) => setNotices((current) => current.filter((item) => item !== notice))}
      />
    </div>
  );
}
