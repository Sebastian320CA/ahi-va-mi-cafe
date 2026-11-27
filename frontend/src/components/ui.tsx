import type { ReactNode } from "react";

type Tone = "ok" | "warn" | "risk" | "info" | "neutral";

const TONES: Record<Tone, string> = {
  ok: "border-ok/40 bg-ok/10 text-ok",
  warn: "border-warn/40 bg-warn/10 text-warn",
  risk: "border-risk/40 bg-risk/10 text-risk",
  info: "border-info/40 bg-info/10 text-info",
  neutral: "border-line bg-sand text-ink/80",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center rounded-sm border px-1.5 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {children}
    </span>
  );
}

export function toneFor(value: string | null | undefined): Tone {
  switch (value) {
    case "no_indications":
    case "reconciled":
    case "resolved":
    case "reviewed":
    case "approved_internal":
      return "ok";
    case "risk_identified":
    case "discrepancy":
    case "open":
    case "not_approved":
      return "risk";
    case "insufficient_information":
    case "incomplete":
    case "pending_verification":
    case "justification_requested":
    case "in_review":
    case "pending_review":
      return "warn";
    case "in_transit":
      return "info";
    default:
      return "neutral";
  }
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <header className="mb-5 flex items-end justify-between gap-4 border-b border-line pb-3">
      <div>
        <h1 className="text-xl font-semibold text-forest">{title}</h1>
        {subtitle ? <p className="mt-1 text-sm text-ink/70">{subtitle}</p> : null}
      </div>
      {actions}
    </header>
  );
}

export function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="mb-5 rounded-sm border border-line bg-paper">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <h2 className="text-sm font-semibold text-coffee">{title}</h2>
        {aside}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-sm border border-line bg-paper px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-ink/60">{label}</div>
      <div className="mt-1 text-lg font-semibold text-forest">{value}</div>
      {hint ? <div className="mt-0.5 text-xs text-ink/60">{hint}</div> : null}
    </div>
  );
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: Tone }) {
  return <div className={`mb-4 rounded-sm border px-3 py-2 text-sm ${TONES[tone]}`}>{children}</div>;
}

export function Loading() {
  return <p className="text-sm text-ink/60">Cargando información...</p>;
}

export function ErrorBox({ message }: { message: string }) {
  return <Notice tone="risk">{message}</Notice>;
}

export function Button({
  children,
  variant = "primary",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" }) {
  const base = "rounded-sm px-3 py-1.5 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed";
  const style =
    variant === "primary"
      ? "bg-forest text-paper hover:bg-forest/90"
      : "border border-line bg-paper text-ink hover:bg-sand";
  return (
    <button {...props} className={`${base} ${style} ${props.className ?? ""}`}>
      {children}
    </button>
  );
}

export const DISCLAIMER =
  "Esta plataforma apoya la recopilación y revisión de evidencias para la diligencia debida. No constituye una certificación ni sustituye las responsabilidades legales del operador.";
