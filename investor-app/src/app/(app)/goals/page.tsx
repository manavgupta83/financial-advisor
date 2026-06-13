/**
 * app/(app)/goals/page.tsx
 * -------------------------
 * Goals page — add goal form with live FV + SIP preview + saved goals list.
 *
 * Schema-verified decisions:
 *   - field is goal_name not name
 *   - inflation_rate sent as decimal (0.06), UI shows %
 *   - years_to_goal validated >= 1 before any API call
 *   - risk_profile + monthly_income come from client fetch
 *   - feasibility_notes is string[] — rendered as list
 *   - client_id resolved same way as dashboard
 */
"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import {
  IconTarget, IconBuilding, IconSchool, IconShield, IconHome,
  IconRings, IconPlane, IconDots, IconTrash, IconPlus, IconRefresh,
} from "@tabler/icons-react";
import api from "@/lib/api";
import { getUser } from "@/lib/auth";
import { Card, Pill, SectionHeader, Spinner, EmptyState, formatINR } from "@/components/ui";
import type { Client, Goal, GoalPlan } from "@/types";

type GoalTypeSlug = "retirement" | "education" | "house" | "emergency" | "wedding" | "travel" | "custom";

interface GoalForm {
  goal_name: string;
  goal_type: GoalTypeSlug;
  target_amount_today: string;
  years_to_goal: string;
  existing_investment: string;
  inflation_rate: string;
  monthly_expense_at_goal: string;
  priority: string;
}

const GOAL_TYPES: { slug: GoalTypeSlug; label: string; icon: React.ReactNode; defaultInflation: string }[] = [
  { slug: "retirement", label: "Retirement", icon: <IconBuilding size={15} />, defaultInflation: "6" },
  { slug: "education",  label: "Education",  icon: <IconSchool   size={15} />, defaultInflation: "8" },
  { slug: "house",      label: "House",      icon: <IconHome     size={15} />, defaultInflation: "7" },
  { slug: "emergency",  label: "Emergency",  icon: <IconShield   size={15} />, defaultInflation: "0" },
  { slug: "wedding",    label: "Wedding",    icon: <IconRings    size={15} />, defaultInflation: "6" },
  { slug: "travel",     label: "Travel",     icon: <IconPlane    size={15} />, defaultInflation: "5" },
  { slug: "custom",     label: "Custom",     icon: <IconDots     size={15} />, defaultInflation: "6" },
];

const EMPTY_FORM: GoalForm = {
  goal_name: "", goal_type: "retirement", target_amount_today: "",
  years_to_goal: "", existing_investment: "", inflation_rate: "6",
  monthly_expense_at_goal: "", priority: "1",
};

function feasibilityVariant(f: string): "success" | "warn" | "danger" | "neutral" {
  if (f === "Feasible")   return "success";
  if (f === "Stretch")    return "warn";
  if (f === "Infeasible") return "danger";
  return "neutral";
}

function goalTypeInfo(slug: string) {
  return GOAL_TYPES.find(g => g.slug === slug) ?? GOAL_TYPES[0];
}

export default function GoalsPage() {
  const user = getUser();
  const [client,       setClient]       = useState<Client | null>(null);
  const [clientId,     setClientId]     = useState<number | null>(null);
  const [goals,        setGoals]        = useState<Goal[]>([]);
  const [goalsLoading, setGoalsLoading] = useState(true);
  const [form,         setForm]         = useState<GoalForm>(EMPTY_FORM);
  const [formOpen,     setFormOpen]     = useState(false);
  const [submitting,   setSubmitting]   = useState(false);
  const [saveError,    setSaveError]    = useState<string | null>(null);
  const [saveSuccess,  setSaveSuccess]  = useState(false);
  const [preview,      setPreview]      = useState<GoalPlan | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [deletingId,   setDeletingId]   = useState<number | null>(null);
  const previewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const resolveClient = useCallback(async () => {
    try {
      if (user?.role === "investor") {
        const { data } = await api.get("/clients/me");
        setClient(data); setClientId(data.id); return data.id as number;
      } else {
        const { data } = await api.get("/clients/");
        if (!data?.length) return null;
        const id = data[0].id as number;
        const cr = await api.get(`/clients/${id}`);
        setClient(cr.data); setClientId(id); return id;
      }
    } catch { return null; }
  }, [user?.role]);

  const fetchGoals = useCallback(async (id: number) => {
    setGoalsLoading(true);
    try { const { data } = await api.get(`/goals/${id}`); setGoals(data); }
    catch { setGoals([]); }
    finally { setGoalsLoading(false); }
  }, []);

  useEffect(() => {
    resolveClient().then(id => { if (id) fetchGoals(id); else setGoalsLoading(false); });
  }, [resolveClient, fetchGoals]);

  const runPreview = useCallback(async (f: GoalForm, c: Client) => {
    const years = parseInt(f.years_to_goal);
    const target = parseFloat(f.target_amount_today) || 0;
    const expense = parseFloat(f.monthly_expense_at_goal) || 0;
    if (isNaN(years) || years < 1 || (!target && !expense)) { setPreview(null); return; }
    setPreviewLoading(true);
    try {
      const { data } = await api.post("/goals/plan", {
        goals: [{
          goal_name: f.goal_name || "My goal", goal_type: f.goal_type,
          target_amount_today: target, years_to_goal: years,
          existing_investment: parseFloat(f.existing_investment) || 0,
          inflation_rate: f.inflation_rate ? parseFloat(f.inflation_rate) / 100 : undefined,
          monthly_expense_at_goal: expense, priority: parseInt(f.priority) || 1,
        }],
        risk_profile: c.risk_profile ?? "Moderate",
        monthly_income: c.monthly_income,
      });
      setPreview(data.plans?.[0] ?? null);
    } catch { setPreview(null); }
    finally { setPreviewLoading(false); }
  }, []);

  useEffect(() => {
    if (!client || !formOpen) return;
    if (previewTimer.current) clearTimeout(previewTimer.current);
    previewTimer.current = setTimeout(() => runPreview(form, client), 600);
    return () => { if (previewTimer.current) clearTimeout(previewTimer.current); };
  }, [form, client, formOpen, runPreview]);

  function updateForm(key: keyof GoalForm, val: string) {
    setForm(prev => {
      const next = { ...prev, [key]: val };
      if (key === "goal_type") {
        const info = GOAL_TYPES.find(g => g.slug === val);
        next.inflation_rate = info?.defaultInflation ?? "6";
        next.goal_name = "";
      }
      return next;
    });
    setSaveSuccess(false); setSaveError(null);
  }

  async function handleSave() {
    if (!clientId) return;
    const years = parseInt(form.years_to_goal);
    if (!form.goal_name.trim() || form.goal_name.trim().length < 2) { setSaveError("Goal name must be at least 2 characters."); return; }
    if (isNaN(years) || years < 1) { setSaveError("Years to goal must be at least 1."); return; }
    setSubmitting(true); setSaveError(null);
    try {
      await api.post(`/goals/${clientId}`, {
        goal_name: form.goal_name.trim(), goal_type: form.goal_type,
        target_amount_today: parseFloat(form.target_amount_today) || 0,
        years_to_goal: years,
        existing_investment: parseFloat(form.existing_investment) || 0,
        inflation_rate: form.inflation_rate ? parseFloat(form.inflation_rate) / 100 : undefined,
        monthly_expense_at_goal: parseFloat(form.monthly_expense_at_goal) || 0,
        priority: parseInt(form.priority) || 1,
      });
      setSaveSuccess(true); setForm(EMPTY_FORM); setPreview(null); setFormOpen(false);
      fetchGoals(clientId);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      if (typeof detail === "string") setSaveError(detail);
      else if (Array.isArray(detail) && detail[0]?.msg) setSaveError(`${detail[0].loc?.slice(-1)[0]}: ${detail[0].msg}`);
      else setSaveError("Could not save goal. Please try again.");
    } finally { setSubmitting(false); }
  }

  async function handleDelete(goalId: number) {
    if (!clientId) return;
    setDeletingId(goalId);
    try { await api.delete(`/goals/${clientId}/${goalId}`); setGoals(prev => prev.filter(g => g.id !== goalId)); }
    catch { }
    finally { setDeletingId(null); }
  }

  const isRetirement = form.goal_type === "retirement";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 500, margin: 0 }}>Goals</h1>
          <p style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 4 }}>
            {client ? `${client.name} · ${client.risk_profile ?? "Not profiled"}` : ""}
          </p>
        </div>
        <button className="btn-primary" style={{ display: "flex", alignItems: "center", gap: 6 }}
          onClick={() => { setFormOpen(o => !o); setSaveError(null); setSaveSuccess(false); }}>
          <IconPlus size={14} /> Add goal
        </button>
      </div>

      {formOpen && (
        <Card>
          <SectionHeader icon={<IconTarget size={15} />} title="New goal" />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 6, marginBottom: 20 }}>
            {GOAL_TYPES.map(gt => (
              <button key={gt.slug} onClick={() => updateForm("goal_type", gt.slug)}
                style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4, padding: "10px 4px", borderRadius: 8, border: "0.5px solid",
                  borderColor: form.goal_type === gt.slug ? "var(--color-accent)" : "var(--color-border)",
                  background: form.goal_type === gt.slug ? "var(--color-accent-light)" : "var(--color-surface)",
                  color: form.goal_type === gt.slug ? "var(--color-accent)" : "var(--color-text-muted)",
                  cursor: "pointer", fontSize: 10, fontWeight: form.goal_type === gt.slug ? 500 : 400, transition: "all 0.15s" }}>
                {gt.icon}{gt.label}
              </button>
            ))}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            <div style={{ gridColumn: "1 / -1" }}>
              <label style={{ fontSize: 11, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>Goal name</label>
              <input className="input" placeholder={`e.g. ${goalTypeInfo(form.goal_type).label} corpus`}
                value={form.goal_name} onChange={e => updateForm("goal_name", e.target.value)} />
            </div>
            {isRetirement ? (
              <div>
                <label style={{ fontSize: 11, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>Monthly expense at retirement (₹)</label>
                <input className="input" type="number" min="0" placeholder="e.g. 100000"
                  value={form.monthly_expense_at_goal} onChange={e => updateForm("monthly_expense_at_goal", e.target.value)} />
              </div>
            ) : (
              <div>
                <label style={{ fontSize: 11, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>Target amount today (₹)</label>
                <input className="input" type="number" min="0" placeholder="e.g. 3000000"
                  value={form.target_amount_today} onChange={e => updateForm("target_amount_today", e.target.value)} />
              </div>
            )}
            <div>
              <label style={{ fontSize: 11, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>Years to goal</label>
              <input className="input" type="number" min="1" max="60" placeholder="e.g. 25"
                value={form.years_to_goal} onChange={e => updateForm("years_to_goal", e.target.value)} />
            </div>
            <div>
              <label style={{ fontSize: 11, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>Existing corpus (₹)</label>
              <input className="input" type="number" min="0" placeholder="e.g. 500000"
                value={form.existing_investment} onChange={e => updateForm("existing_investment", e.target.value)} />
            </div>
            <div>
              <label style={{ fontSize: 11, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>Inflation rate (%)</label>
              <input className="input" type="number" min="0" max="30" step="0.5"
                value={form.inflation_rate} onChange={e => updateForm("inflation_rate", e.target.value)} />
            </div>
          </div>

          {previewLoading && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 16, padding: "12px 0", borderTop: "0.5px solid var(--color-border)" }}>
              <Spinner size={14} />
              <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>Calculating…</span>
            </div>
          )}

          {preview && !previewLoading && (
            <div style={{ marginTop: 16, padding: 16, background: "var(--color-accent-light)", borderRadius: 10, border: "0.5px solid var(--color-accent)" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                <span style={{ fontSize: 12, fontWeight: 500, color: "var(--color-accent-dark)" }}>Live preview</span>
                <Pill variant={feasibilityVariant(preview.feasibility)}>{preview.feasibility}</Pill>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
                {[
                  { label: "Future value",    val: formatINR(preview.future_value) },
                  { label: "Monthly SIP",     val: formatINR(preview.adjusted_sip) },
                  { label: "Expected return", val: `${(preview.expected_annual_return * 100).toFixed(1)}% p.a.` },
                ].map(({ label, val }) => (
                  <div key={label}>
                    <p style={{ fontSize: 10, color: "var(--color-accent-dark)", marginBottom: 2 }}>{label}</p>
                    <p style={{ fontSize: 15, fontWeight: 500, color: "var(--color-accent-dark)" }}>{val}</p>
                  </div>
                ))}
              </div>
              {Array.isArray(preview.feasibility_notes) && preview.feasibility_notes.length > 0 && (
                <div style={{ marginTop: 10, paddingTop: 10, borderTop: "0.5px solid rgba(8,145,178,0.2)" }}>
                  {(preview.feasibility_notes as string[]).map((note: string, i: number) => (
                    <p key={i} style={{ fontSize: 11, color: "var(--color-accent-dark)", marginBottom: 2 }}>· {note}</p>
                  ))}
                </div>
              )}
            </div>
          )}

          {saveError && (
            <p style={{ fontSize: 11, color: "var(--color-negative)", background: "var(--color-negative-light)", borderRadius: 8, padding: "8px 12px", marginTop: 12 }}>{saveError}</p>
          )}

          <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
            <button className="btn-primary" disabled={submitting} onClick={handleSave}
              style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {submitting ? <Spinner size={14} /> : null}{submitting ? "Saving…" : "Save goal"}
            </button>
            <button className="btn-secondary"
              onClick={() => { setFormOpen(false); setForm(EMPTY_FORM); setPreview(null); setSaveError(null); }}>
              Cancel
            </button>
          </div>
        </Card>
      )}

      {saveSuccess && (
        <div style={{ background: "#F0FDF4", border: "0.5px solid #86efac", borderRadius: 10, padding: "12px 16px", fontSize: 12, color: "#166534" }}>
          Goal saved successfully.
        </div>
      )}

      <Card>
        <SectionHeader icon={<IconTarget size={15} />}
          title={`Saved goals${goals.length ? ` (${goals.length})` : ""}`}
          action={clientId ? (
            <button onClick={() => fetchGoals(clientId)}
              style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-text-muted)", display: "flex", alignItems: "center", gap: 4, fontSize: 11 }}>
              <IconRefresh size={12} /> Refresh
            </button>
          ) : null}
        />
        {goalsLoading ? (
          <div style={{ display: "flex", justifyContent: "center", padding: "2rem 0" }}><Spinner size={24} /></div>
        ) : goals.length === 0 ? (
          <EmptyState icon={<IconTarget />} title="No goals yet" description="Add your first goal above to get started." />
        ) : (
          <div>
            {goals.map(g => {
              const info = goalTypeInfo(g.goal_type);
              return (
                <div key={g.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 0", borderBottom: "0.5px solid var(--color-border)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <div style={{ width: 32, height: 32, borderRadius: 8, background: "var(--color-accent-light)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--color-accent)", flexShrink: 0 }}>{info.icon}</div>
                    <div>
                      <p style={{ fontSize: 13, fontWeight: 500 }}>{g.goal_name}</p>
                      <p style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>{info.label} · Target {g.target_year} · {formatINR(g.target_amount)}</p>
                    </div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <div style={{ textAlign: "right" }}>
                      <p style={{ fontSize: 13, fontWeight: 500, color: "var(--color-accent)" }}>{formatINR(g.monthly_sip)}/mo</p>
                      <p style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{formatINR(g.current_savings)} existing</p>
                    </div>
                    <button onClick={() => handleDelete(g.id)} disabled={deletingId === g.id}
                      style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-text-muted)", padding: 4, display: "flex", alignItems: "center" }}>
                      {deletingId === g.id ? <Spinner size={14} /> : <IconTrash size={14} />}
                    </button>
                  </div>
                </div>
              );
            })}
            {goals.length > 1 && (
              <div style={{ display: "flex", justifyContent: "space-between", padding: "12px 0 0", marginTop: 4 }}>
                <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>Total monthly SIP</span>
                <span style={{ fontSize: 14, fontWeight: 500, color: "var(--color-accent)" }}>
                  {formatINR(goals.reduce((sum, g) => sum + g.monthly_sip, 0))}/mo
                </span>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
