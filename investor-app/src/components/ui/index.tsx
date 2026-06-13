/**
 * components/ui/index.tsx — Design system primitives
 * Card, HeroCard, Pill, SectionHeader, Spinner, EmptyState, StatRow, formatINR, formatPct
 */
import React from "react";
import { clsx } from "clsx";

export function Card({ children, className, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={clsx('card', className)} {...rest}>{children}</div>;
}

export function HeroCard({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={clsx('hero-card', className)}>{children}</div>;
}

export type PillVariant = "accent" | "success" | "warn" | "danger" | "neutral";
const pillMap: Record<PillVariant, string> = {
  accent: 'pill-accent', success: 'pill-success', warn: 'pill-warn', danger: 'pill-danger', neutral: 'pill-neutral',
};
export function Pill({ children, variant = 'neutral', className, style }: { children: React.ReactNode; variant?: PillVariant; className?: string; style?: React.CSSProperties }) {
  return <span className={clsx('pill', pillMap[variant], className)} style={style}>{children}</span>;
}

export function SectionHeader({ icon, title, action }: { icon: React.ReactNode; title: string; action?: React.ReactNode; }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 500 }}>
        <span style={{ color: 'var(--color-accent)', display: 'flex', width: 15, height: 15 }}>{icon}</span>
        {title}
      </div>
      {action}
    </div>
  );
}

export function Spinner({ size = 20, className }: { size?: number; className?: string }) {
  return (
    <svg className={clsx('animate-spin', className)} width={size} height={size} viewBox="0 0 24 24" fill="none" style={{ color: 'var(--color-accent)' }} aria-label="Loading">
      <circle style={{ opacity: 0.25 }} cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path style={{ opacity: 0.75 }} fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

export function EmptyState({ icon, title, description, action }: { icon: React.ReactNode; title: string; description?: string; action?: React.ReactNode; }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '4rem 0', textAlign: 'center', gap: 12 }}>
      <div style={{ fontSize: 40, color: 'var(--color-text-muted)', opacity: 0.4 }}>{icon}</div>
      <p style={{ fontSize: 13, fontWeight: 500 }}>{title}</p>
      {description && <p style={{ fontSize: 13, color: 'var(--color-text-muted)', maxWidth: 280 }}>{description}</p>}
      {action && <div style={{ marginTop: 8 }}>{action}</div>}
    </div>
  );
}

export function StatRow({ label, value, className }: { label: string; value: React.ReactNode; className?: string }) {
  return (
    <div className={clsx('trow', className)} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '0.5px solid var(--color-border)' }}>
      <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 500 }}>{value}</span>
    </div>
  );
}

export function formatINR(val: number): string {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(val);
}
export function formatPct(val: number, digits = 1): string {
  return `${val >= 0 ? '+' : ''}${val.toFixed(digits)}%`;
}
