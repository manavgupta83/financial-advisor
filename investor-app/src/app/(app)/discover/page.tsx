/**
 * app/(app)/discover/page.tsx
 * Fund screener + factsheet drawer with NAV chart, top holdings, AI summary.
 */
"use client";
import { useState, useCallback } from "react";
import {
  IconSearch, IconChartLine, IconInfoCircle,
  IconChevronRight, IconSparkles, IconArrowLeft,
} from "@tabler/icons-react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import api from "@/lib/api";
import { Card, SectionHeader, Spinner, EmptyState, Pill } from "@/components/ui";

interface FundSummary {
  scheme_code: number; scheme_name: string;
  fund_house: string | null; category: string | null;
  sub_category: string | null; plan_type: string | null; ai_summary: string | null;
}
interface TopHolding { stock_name: string; isin: string; weight_pct: number; sector: string | null; }
interface NavPoint { nav_date: string; nav: number; }
interface Factsheet extends FundSummary { nav_history: NavPoint[]; top_holdings: TopHolding[]; }

export default function DiscoverPage() {
  const [search,     setSearch]     = useState("");
  const [category,   setCategory]   = useState("");
  const [fundHouse,  setFundHouse]  = useState("");
  const [planType,   setPlanType]   = useState("");
  const [page,       setPage]       = useState(1);
  const [results,    setResults]    = useState<FundSummary[]>([]);
  const [loading,    setLoading]    = useState(false);
  const [searched,   setSearched]   = useState(false);
  const [factsheet,  setFactsheet]  = useState<Factsheet | null>(null);
  const [fsLoading,  setFsLoading]  = useState(false);
  const [selectedCode, setSelectedCode] = useState<number | null>(null);

  const runSearch = useCallback(async (p = 1) => {
    setLoading(true); setSearched(true);
    try {
      const params = new URLSearchParams({ page: String(p), page_size: "20" });
      if (search)    params.set("search",     search);
      if (category)  params.set("category",   category);
      if (fundHouse) params.set("fund_house", fundHouse);
      if (planType)  params.set("plan_type",  planType);
      const { data } = await api.get(`/funds/screen?${params}`);
      setResults(data); setPage(p);
    } catch { setResults([]); }
    finally { setLoading(false); }
  }, [search, category, fundHouse, planType]);

  function handleKeyDown(e: React.KeyboardEvent) { if (e.key === "Enter") runSearch(1); }

  async function openFactsheet(code: number) {
    setSelectedCode(code); setFactsheet(null); setFsLoading(true);
    try { const { data } = await api.get(`/funds/${code}`); setFactsheet(data); }
    catch { setFactsheet(null); }
    finally { setFsLoading(false); }
  }

  function closeFactsheet() { setSelectedCode(null); setFactsheet(null); }
  function fmtDate(d: string) { return new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short" }); }
  function planPill(pt: string | null) {
    if (!pt) return null;
    return <Pill variant={pt === "Direct" ? "accent" : "neutral"} className="text-[10px]">{pt}</Pill>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        <h1 style={{ fontSize: 20, fontWeight: 500, margin: 0 }}>Discover</h1>
        <p style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 4 }}>Search across 14,000+ mutual funds</p>
      </div>

      <Card style={{ padding: "14px 16px" }}>
        <div style={{ display: "flex", gap: 10, marginBottom: 12 }}>
          <div style={{ flex: 1, position: "relative" }}>
            <IconSearch size={14} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--color-text-muted)" }} />
            <input className="input" style={{ paddingLeft: 32 }} placeholder="Search by fund name e.g. Parag Parikh, Mirae…"
              value={search} onChange={e => setSearch(e.target.value)} onKeyDown={handleKeyDown} />
          </div>
          <button className="btn-primary" onClick={() => runSearch(1)} style={{ display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
            {loading ? <Spinner size={14} /> : <IconSearch size={14} />} Search
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
          <div>
            <label style={{ fontSize: 10, color: "var(--color-text-muted)", display: "block", marginBottom: 3 }}>Category</label>
            <input className="input" style={{ fontSize: 12 }} placeholder="e.g. Flexi Cap Fund"
              value={category} onChange={e => setCategory(e.target.value)} onKeyDown={handleKeyDown} />
          </div>
          <div>
            <label style={{ fontSize: 10, color: "var(--color-text-muted)", display: "block", marginBottom: 3 }}>Fund house</label>
            <input className="input" style={{ fontSize: 12 }} placeholder="e.g. PPFAS, Mirae"
              value={fundHouse} onChange={e => setFundHouse(e.target.value)} onKeyDown={handleKeyDown} />
          </div>
          <div>
            <label style={{ fontSize: 10, color: "var(--color-text-muted)", display: "block", marginBottom: 3 }}>Plan type</label>
            <select className="input" style={{ fontSize: 12 }} value={planType} onChange={e => setPlanType(e.target.value)}>
              <option value="">All</option>
              <option value="Direct">Direct</option>
              <option value="Regular">Regular</option>
            </select>
          </div>
        </div>
      </Card>

      {!searched && !loading && <EmptyState icon={<IconSearch />} title="Search for a fund" description="Enter a fund name, category, or AMC to get started." />}
      {loading && <div style={{ display: "flex", justifyContent: "center", padding: "3rem 0" }}><Spinner size={24} /></div>}
      {searched && !loading && results.length === 0 && <EmptyState icon={<IconSearch />} title="No funds found" description="Try a different search term or remove some filters." />}

      {results.length > 0 && !loading && (
        <Card>
          <SectionHeader icon={<IconSearch size={15} />} title={`Results (${results.length})`} />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 160px 120px 80px 36px", gap: 8, padding: "6px 0", borderBottom: "0.5px solid var(--color-border)", marginBottom: 4 }}>
            {["Fund", "Category", "AMC", "Plan", ""].map(h => (
              <span key={h} style={{ fontSize: 10, color: "var(--color-text-muted)", fontWeight: 500 }}>{h}</span>
            ))}
          </div>
          {results.map(f => (
            <div key={f.scheme_code}
              style={{ display: "grid", gridTemplateColumns: "1fr 160px 120px 80px 36px", gap: 8, padding: "10px 0", borderBottom: "0.5px solid var(--color-border)", alignItems: "center", cursor: "pointer" }}
              onClick={() => openFactsheet(f.scheme_code)}>
              <div style={{ minWidth: 0 }}>
                <p style={{ fontSize: 12, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.scheme_name}</p>
                {f.sub_category && <p style={{ fontSize: 10, color: "var(--color-text-muted)", marginTop: 2 }}>{f.sub_category}</p>}
              </div>
              <span style={{ fontSize: 11, color: "var(--color-text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.category ?? "—"}</span>
              <span style={{ fontSize: 11, color: "var(--color-text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.fund_house ?? "—"}</span>
              <span>{planPill(f.plan_type)}</span>
              <IconChevronRight size={14} style={{ color: "var(--color-text-muted)" }} />
            </div>
          ))}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 14 }}>
            <button className="btn-secondary" disabled={page <= 1} onClick={() => runSearch(page - 1)} style={{ fontSize: 12, padding: "6px 14px" }}>Previous</button>
            <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>Page {page}</span>
            <button className="btn-secondary" disabled={results.length < 20} onClick={() => runSearch(page + 1)} style={{ fontSize: 12, padding: "6px 14px" }}>Next</button>
          </div>
        </Card>
      )}

      {selectedCode !== null && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 100, display: "flex", justifyContent: "flex-end" }} onClick={closeFactsheet}>
          <div style={{ width: "min(560px, 100vw)", height: "100vh", background: "var(--color-surface)", overflowY: "auto", padding: 24, boxShadow: "-4px 0 24px rgba(0,0,0,0.1)" }}
            onClick={e => e.stopPropagation()}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
              <button onClick={closeFactsheet} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-text-muted)", display: "flex", padding: 4 }}>
                <IconArrowLeft size={18} />
              </button>
              <span style={{ fontSize: 13, fontWeight: 500 }}>Fund factsheet</span>
            </div>
            {fsLoading && <div style={{ display: "flex", justifyContent: "center", padding: "4rem 0" }}><Spinner size={28} /></div>}
            {factsheet && !fsLoading && (
              <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                <div>
                  <h2 style={{ fontSize: 16, fontWeight: 500, margin: "0 0 8px" }}>{factsheet.scheme_name}</h2>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {factsheet.fund_house && <span className="pill pill-neutral" style={{ fontSize: 10 }}>{factsheet.fund_house}</span>}
                    {factsheet.category && <span className="pill pill-neutral" style={{ fontSize: 10 }}>{factsheet.category}</span>}
                    {planPill(factsheet.plan_type)}
                  </div>
                </div>
                {factsheet.ai_summary && (
                  <div style={{ background: "var(--color-accent-light)", borderRadius: 10, padding: 14, border: "0.5px solid var(--color-accent)" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8, fontSize: 12, fontWeight: 500, color: "var(--color-accent-dark)" }}>
                      <IconSparkles size={14} /> AI summary
                    </div>
                    <p style={{ fontSize: 12, color: "var(--color-accent-dark)", lineHeight: 1.6 }}>{factsheet.ai_summary}</p>
                  </div>
                )}
                {factsheet.nav_history.length > 0 ? (
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 12, fontSize: 13, fontWeight: 500 }}>
                      <IconChartLine size={15} style={{ color: "var(--color-accent)" }} /> NAV history (1yr)
                    </div>
                    <ResponsiveContainer width="100%" height={180}>
                      <LineChart data={factsheet.nav_history} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
                        <XAxis dataKey="nav_date" tickFormatter={fmtDate} tick={{ fontSize: 10, fill: "#888" }} interval="preserveStartEnd" />
                        <YAxis tick={{ fontSize: 10, fill: "#888" }} domain={["auto", "auto"]} width={50} tickFormatter={v => `₹${v}`} />
                        <Tooltip formatter={(v: unknown) => [`₹${Number(v).toFixed(2)}`, "NAV"]}
                          labelFormatter={(d: unknown) => fmtDate(String(d))}
                          contentStyle={{ fontSize: 11, borderRadius: 8, border: "0.5px solid var(--color-border)" }} />
                        <Line type="monotone" dataKey="nav" stroke="#0891B2" strokeWidth={1.5} dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <div style={{ background: "#F8FAFB", borderRadius: 8, padding: 14, fontSize: 12, color: "var(--color-text-muted)", textAlign: "center" }}>No NAV history available.</div>
                )}
                {factsheet.top_holdings.length > 0 && (
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 12, fontSize: 13, fontWeight: 500 }}>
                      <IconInfoCircle size={15} style={{ color: "var(--color-accent)" }} /> Top holdings
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 100px 70px", gap: 6, padding: "5px 0", borderBottom: "0.5px solid var(--color-border)", marginBottom: 4 }}>
                      {["Stock", "Sector", "Weight"].map(h => <span key={h} style={{ fontSize: 10, color: "var(--color-text-muted)", fontWeight: 500 }}>{h}</span>)}
                    </div>
                    {factsheet.top_holdings.map((h, i) => (
                      <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 100px 70px", gap: 6, padding: "8px 0", borderBottom: "0.5px solid var(--color-border)", alignItems: "center" }}>
                        <p style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{h.stock_name}</p>
                        <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{h.sector ?? "—"}</span>
                        <span style={{ fontSize: 12, fontWeight: 500, color: "var(--color-accent)" }}>{h.weight_pct.toFixed(2)}%</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
