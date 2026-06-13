/**
 * app/(auth)/login/page.tsx
 * OTP login — Step 1: email → Step 2: OTP → JWT saved → redirect
 * Investor/Advisor toggle (same flow, different post-login redirect label)
 * DEV: API returns otp_dev in response for local testing
 */
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { IconMail, IconShieldCheck, IconTrendingUp, IconRefresh } from "@tabler/icons-react";
import api from "@/lib/api";
import { saveTokens } from "@/lib/auth";
import { Spinner } from "@/components/ui";
import { clsx } from "clsx";

type Role = "investor" | "advisor";
type Step = "email" | "otp";

export default function LoginPage() {
  const router = useRouter();
  const [role, setRole]       = useState<Role>("investor");
  const [step, setStep]       = useState<Step>("email");
  const [email, setEmail]     = useState("");
  const [otp, setOtp]         = useState("");
  const [devOtp, setDevOtp]   = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  async function handleRequestOtp(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { data } = await api.post("/auth/request-otp", { email });
      if (data.otp_dev) setDevOtp(data.otp_dev);
      setStep("otp");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || "Could not send OTP. Check the email and try again.");
    } finally {
      setLoading(false);
    }
  }

  async function handleVerifyOtp(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { data } = await api.post("/auth/verify-otp", { email, otp });
      saveTokens(data.access_token, data.refresh_token);
      router.replace("/dashboard");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || "Invalid or expired OTP. Try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ width: '100%', maxWidth: 384 }}>
      <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <IconTrendingUp size={24} style={{ color: '#0891B2' }} />
          <span style={{ fontSize: 20, fontWeight: 500, letterSpacing: '-0.3px' }}>
            mf<span style={{ color: '#0891B2' }}>advisory</span>
          </span>
        </div>
        <p style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>Goal-based investing, made simple</p>
      </div>

      <div style={{ display: 'flex', background: '#F3F4F6', borderRadius: 20, border: '0.5px solid var(--color-border)', padding: 4, marginBottom: '1.5rem' }}>
        {(['investor', 'advisor'] as Role[]).map((r) => (
          <button key={r} onClick={() => { setRole(r); setError(null); }}
            style={{
              flex: 1, padding: '8px 0', borderRadius: 20, border: 'none', fontSize: 11, fontWeight: 500,
              cursor: 'pointer', textTransform: 'capitalize', transition: 'all 0.15s',
              background: role === r ? 'var(--color-surface)' : 'transparent',
              color: role === r ? 'var(--color-text-primary)' : 'var(--color-text-muted)',
              boxShadow: role === r ? '0 1px 3px rgba(0,0,0,0.06)' : 'none',
            }}>
            {r === 'investor' ? 'Investor' : 'Advisor'}
          </button>
        ))}
      </div>

      <div className="card" style={{ padding: '1.5rem' }}>
        {step === 'email' ? (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <IconMail size={15} style={{ color: '#0891B2' }} />
              <span style={{ fontSize: 13, fontWeight: 500 }}>Sign in</span>
            </div>
            <p style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: '1.25rem' }}>
              {role === 'investor' ? 'Enter your registered email to receive a one-time password.' : 'Enter your advisor email to access your client dashboard.'}
            </p>
            <form onSubmit={handleRequestOtp} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div>
                <label style={{ fontSize: 11, color: 'var(--color-text-muted)', display: 'block', marginBottom: 4 }}>Email address</label>
                <input type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com" className="input" />
              </div>
              {error && <p style={{ fontSize: 11, color: 'var(--color-negative)', background: 'var(--color-negative-light)', borderRadius: 8, padding: '8px 12px' }}>{error}</p>}
              <button type="submit" disabled={loading} className="btn-primary" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                {loading && <Spinner size={16} />}{loading ? 'Sending…' : 'Send OTP'}
              </button>
            </form>
          </>
        ) : (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <IconShieldCheck size={15} style={{ color: '#0891B2' }} />
              <span style={{ fontSize: 13, fontWeight: 500 }}>Enter OTP</span>
            </div>
            <p style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 4 }}>A 6-digit code was sent to</p>
            <p style={{ fontSize: 13, fontWeight: 500, marginBottom: '1.25rem' }}>{email}</p>
            {devOtp && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'var(--color-accent-light)', borderRadius: 8, padding: '8px 12px', marginBottom: 16 }}>
                <span style={{ fontSize: 11, color: 'var(--color-accent-dark)' }}>Dev OTP:</span>
                <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--color-accent)', cursor: 'pointer', textDecoration: 'underline' }}
                  onClick={() => setOtp(devOtp)}>{devOtp} (click to fill)</span>
              </div>
            )}
            <form onSubmit={handleVerifyOtp} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div>
                <label style={{ fontSize: 11, color: 'var(--color-text-muted)', display: 'block', marginBottom: 4 }}>One-time password</label>
                <input type="text" inputMode="numeric" maxLength={6} pattern="\d{6}" required autoFocus
                  value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
                  placeholder="123456" className="input" style={{ letterSpacing: '0.2em', fontSize: 18, fontWeight: 500 }} />
              </div>
              {error && <p style={{ fontSize: 11, color: 'var(--color-negative)', background: 'var(--color-negative-light)', borderRadius: 8, padding: '8px 12px' }}>{error}</p>}
              <button type="submit" disabled={loading} className="btn-primary" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                {loading && <Spinner size={16} />}{loading ? 'Verifying…' : 'Sign in'}
              </button>
              <button type="button" onClick={() => { setStep('email'); setOtp(''); setError(null); setDevOtp(null); }}
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, fontSize: 11, color: 'var(--color-text-muted)', background: 'none', border: 'none', cursor: 'pointer' }}>
                <IconRefresh size={13} /> Use a different email
              </button>
            </form>
          </>
        )}
      </div>
      <p style={{ textAlign: 'center', fontSize: 11, color: 'var(--color-text-muted)', marginTop: '1.5rem' }}>No password needed · Secure OTP login</p>
    </div>
  );
}
