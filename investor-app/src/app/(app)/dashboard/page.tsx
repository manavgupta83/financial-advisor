/**
 * app/(app)/dashboard/page.tsx
 * Works for advisor role (current) and investor role (future).
 * Advisor: GET /clients/ -> use data[0].id for all portfolio calls
 * Investor: GET /clients/me -> use own id
 * Note: feasibility pill removed — GET /goals/{id} does not return feasibility
 */
"use client";
import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  IconTrendingUp, IconTrendingDown, IconCoins, IconStack2,
  IconTarget, IconBuilding, IconSchool, IconShield, IconHome,
  IconChartPie, IconBriefcase, IconUser, IconArrowRight, IconCalendar,
} from "@tabler/icons-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import api from "@/lib/api";
import { getUser } from "@/lib/auth";
import { Card, HeroCard, Pill, SectionHeader, Spinner, EmptyState, formatINR, formatPct } from "@/components/ui";
import type { Client, PortfolioSummary, Goal, Holding } from "@/types";

interface SectorItem { sector: string; weight: number; }

const GOAL_ICONS: Record<string, React.ReactNode> = {
  retirement: <IconBuilding size={13} />,
  education:  <IconSchool   size={13} />,
  emergency:  <IconShield   size={13} />,
  house:      <IconHome     size={13} />,
};
function goalIcon(type: string) { return GOAL_ICONS[type] ?? <IconTarget size={13} />; }

export default function DashboardPage() {
  const user = getUser();
  const [client,   setClient]   = useState<Client | null>(null);
  const [clientId, setClientId] = useState<number | null>(null);
  const [summary,  setSummary]  = useState<PortfolioSummary | null>(null);
  const [goals,    setGoals]    = useState<Goal[]>([]);
  const [sectors,  setSectors]  = useState<SectorItem[]>([]);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let resolvedClientId: number;
      let resolvedClient: Client;

      if (user?.role === "investor") {
        const { data } = await api.get("/clients/me");
        resolvedClient = data;
        resolvedClientId = data.id;
      } else {
        const { data } = await api.get("/clients/");
        if (!data || data.length === 0) {
          setError("No clients assigned to your account yet.");
          setLoading(false);
          return;
        }
        resolvedClientId = data[0].id;
        const clientRes = await api.get(`/clients/${resolvedClientId}`);
        resolvedClient = clientRes.data;
      }

      setClientId(resolvedClientId);
      setClient(resolvedClient);

      const [sRes, gRes, secRes, hRes] = await Promise.allSettled([
        api.get(`/portfolio/${resolvedClientId}/summary`),
        api.get(`/goals/${resolvedClientId}`),
        api.get(`/portfolio/${resolvedClientId}/sector-allocation`),
        api.get(`/holdings/${resolvedClientId}`),
      ]);

      if (sRes.status === "fulfilled") setSummary(sRes.value.data);
      if (gRes.status === "fulfilled") setGoals(gRes.value.data);
      if (secRes.status === "fulfilled") {
        const raw = secRes.value.data;
        const items: Array<{sector: string; weight_pct: number}> = raw.allocations ?? [];
        setSectors(
          items
            .map(i => ({ sector: i.sector, weight: i.weight_pct }))
            .sort((a, b) => b.weight - a.weight)
            .slice(0, 6)
        );
      }
      if (hRes.status === "fulfilled") setHoldings((hRes.value.data as Holding[]).slice(0, 4));

    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || "Could not load portfolio. Make sure the API is running.");
    } finally {
      setLoading(false);
    }
  }, [user?.role]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  if (loading) return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 256 }}>
      <Spinner size={28} />
    </div>
  );

  if (error) return (
    <EmptyState icon={<IconTrendingUp />} title="Could not load dashboard" description={error}
      action={<button onClick={fetchAll} className="btn-primary">Retry</button>} />
  );

  const gainPositive = (summary?.absolute_gain ?? 0) >= 0;
  const firstName    = client?.name?.split(" ")[0] ?? "there";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

      <HeroCard>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 16 }}>
          <div>
            <p style={{ fontSize: 11, opacity: 0.8, marginBottom: 4 }}>Good morning, {firstName}</p>
            <p style={{ fontSize: 28, fontWeight: 500, letterSpacing: "-0.5px", lineHeight: 1, marginBottom: 8 }}>
              {formatINR(summary?.total_current ?? 0)}
            </p>
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, opacity: 0.9 }}>
              {gainPositive ? <IconTrendingUp size={14} /> : <IconTrendingDown size={14} />}
              <span>{formatINR(Math.abs(summary?.absolute_gain ?? 0))} &nbsp;·&nbsp; {formatPct(summary?.gain_percentage ?? 0)} overall</span>
            </div>
          </div>
          <div style={{ textAlign: "right", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
            <span className="pill" style={{ background: "rgba(255,255,255,0.2)", color: "white" }}>
              {client?.risk_profile ?? "Not profiled"}
            </span>
            <div style={{ fontSize: 12, opacity: 0.85 }}>
              ₹{((summary?.total_invested ?? 0) * 0.033).toLocaleString("en-IN", { maximumFractionDigits: 0 })} / month SIP
            </div>
          </div>
        </div>
      </HeroCard>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
        {[
          { icon: <IconCoins size={13} />,    label: "Invested",  val: formatINR(summary?.total_invested ?? 0) },
          { icon: <IconStack2 size={13} />,   label: "Holdings",  val: `${summary?.num_holdings ?? 0} funds` },
          { icon: <IconCalendar size={13} />, label: "NAV date",  val: new Date().toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) },
        ].map(({ icon, label, val }) => (
          <Card key={label}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--color-text-muted)", marginBottom: 6 }}>
              <span style={{ color: "var(--color-accent)" }}>{icon}</span>{label}
            </div>
            <p style={{ fontSize: 17, fontWeight: 500 }}>{val}</p>
          </Card>
        ))}
      </div>

      <Card>
        <SectionHeader icon={<IconTarget size={15} />} title="Goals"
          action={
            <Link href="/goals" style={{ fontSize: 11, color: "var(--color-accent)", display: "flex", alignItems: "center", gap: 4, textDecoration: "none" }}>
              Manage <IconArrowRight size={12} />
            </Link>
          }
        />
        {goals.length === 0
          ? <EmptyState icon={<IconTarget />} title="No goals yet" description="Add your first goal to get a fund recommendation."
              action={<Link href="/goals" className="btn-primary">Add goal</Link>} />
          : goals.map((g) => (
            <div key={g.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 0", borderBottom: "0.5px solid var(--color-border)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ color: "var(--color-accent)" }}>{goalIcon(g.goal_type)}</span>
                <div>
                  <p style={{ fontSize: 13 }}>{g.goal_name}</p>
                  <p style={{ fontSize: 11, color: "var(--color-text-muted)" }}>Target {g.target_year} · {formatINR(g.target_amount)}</p>
                </div>
              </div>
              <p style={{ fontSize: 13, fontWeight: 500, color: "var(--color-accent)" }}>{formatINR(g.monthly_sip)}/mo</p>
            </div>
          ))
        }
      </Card>

      {sectors.length > 0 && (
        <Card>
          <SectionHeader icon={<IconChartPie size={15} />} title="Sector allocation" />
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={sectors} layout="vertical" margin={{ left: 0, right: 24, top: 0, bottom: 0 }}>
              <XAxis type="number" domain={[0, 40]} tick={{ fontSize: 10, fill: "#888" }} tickFormatter={(v) => `${v}%`} />
              <YAxis type="category" dataKey="sector" tick={{ fontSize: 11, fill: "#444" }} width={120} />
              <Tooltip formatter={(v: unknown) => [`${v}%`, "Weight"]} contentStyle={{ fontSize: 12, borderRadius: 8, border: "0.5px solid #E8EAEC" }} />
              <Bar dataKey="weight" radius={[0, 4, 4, 0]}>
                {sectors.map((_, i) => <Cell key={i} fill={i === 0 ? "#0891B2" : `rgba(8,145,178,${Math.max(0.2, 0.7 - i * 0.1)})`} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>
      )}

      {holdings.length > 0 && (
        <Card>
          <SectionHeader icon={<IconBriefcase size={15} />} title="Holdings"
            action={
              <Link href="/holdings" style={{ fontSize: 11, color: "var(--color-accent)", display: "flex", alignItems: "center", gap: 4, textDecoration: "none" }}>
                View all <IconArrowRight size={12} />
              </Link>
            }
          />
          {holdings.map((h) => (
            <div key={h.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 0", borderBottom: "0.5px solid var(--color-border)" }}>
              <div style={{ flex: 1, minWidth: 0, paddingRight: 16 }}>
                <p style={{ fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{h.scheme_name}</p>
                <p style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{formatINR(h.invested_amount)} invested</p>
              </div>
              <div style={{ textAlign: "right", flexShrink: 0 }}>
                <p style={{ fontSize: 13, fontWeight: 500 }}>{formatINR(h.current_value)}</p>
                <p style={{ fontSize: 11, color: (h.cagr ?? 0) >= 0 ? "var(--color-positive)" : "var(--color-negative)" }}>
                  {h.cagr != null ? `${formatPct(h.cagr)} CAGR` : "—"}
                </p>
              </div>
            </div>
          ))}
        </Card>
      )}

      <Card style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ width: 36, height: 36, borderRadius: 20, background: "var(--color-accent-light)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          <IconUser size={16} style={{ color: "var(--color-accent)" }} />
        </div>
        <div style={{ flex: 1 }}>
          <p style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
            {user?.role === "advisor" ? "Viewing client" : "Your advisor"}
          </p>
          <p style={{ fontSize: 13, fontWeight: 500 }}>
            {client?.name ?? "—"} {clientId ? `(ID: ${clientId})` : ""}
          </p>
        </div>
        <button className="btn-secondary" style={{ fontSize: 11, padding: "6px 12px" }}>Request review</button>
      </Card>
    </div>
  );
}
