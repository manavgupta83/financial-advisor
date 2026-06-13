/**
 * app/(app)/holdings/page.tsx
 * Holdings: summary strip, holdings table, overlap matrix, statement upload (two-step)
 * Schema-verified: blended_xirr/cagr already %, overlap_pct already %, cagr nullable
 */
"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import {
  IconBriefcase, IconUpload, IconTrash, IconChartDots,
  IconRefresh, IconAlertTriangle, IconCheck, IconX,
} from "@tabler/icons-react";
import api from "@/lib/api";
import { getUser } from "@/lib/auth";
import { Card, SectionHeader, Spinner, EmptyState, formatINR, formatPct } from "@/components/ui";
import type { Client, Holding, PortfolioSummary } from "@/types";

interface OverlapPair {
  fund_a_code: number; fund_a_name: string;
  fund_b_code: number; fund_b_name: string;
  overlap_pct: number; warning_level: string;
}
interface UploadPreview { preview: unknown; message: string; raw: Record<string, unknown>; }

function overlapColour(level: string) {
  if (level === "high")   return { bg: "#FEF2F2", text: "#991B1B" };
  if (level === "medium") return { bg: "#FEF9EC", text: "#92400E" };
  if (level === "low")    return { bg: "#ECFEFF", text: "#0E7490" };
  return { bg: "#F3F4F6", text: "#374151" };
}

export default function HoldingsPage() {
  const user = getUser();
  const [client,      setClient]      = useState<Client | null>(null);
  const [clientId,    setClientId]    = useState<number | null>(null);
  const [holdings,    setHoldings]    = useState<Holding[]>([]);
  const [summary,     setSummary]     = useState<PortfolioSummary | null>(null);
  const [overlap,     setOverlap]     = useState<OverlapPair[]>([]);
  const [warnings,    setWarnings]    = useState<string[]>([]);
  const [loading,     setLoading]     = useState(true);
  const [deletingId,  setDeletingId]  = useState<number | null>(null);
  const [uploading,   setUploading]   = useState(false);
  const [uploadPreview, setUploadPreview] = useState<UploadPreview | null>(null);
  const [confirming,  setConfirming]  = useState(false);
  const [uploadDone,  setUploadDone]  = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

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

  const fetchAll = useCallback(async (id: number) => {
    setLoading(true);
    const [hRes, sRes, oRes] = await Promise.allSettled([
      api.get(`/holdings/${id}`),
      api.get(`/portfolio/${id}/summary`),
      api.get(`/portfolio/${id}/overlap`),
    ]);
    if (hRes.status === "fulfilled") {
      const seen = new Set<number>();
      setHoldings((hRes.value.data as Holding[]).filter(h => {
        if (seen.has(h.scheme_code)) return false; seen.add(h.scheme_code); return true;
      }));
    }
    if (sRes.status === "fulfilled") setSummary(sRes.value.data);
    if (oRes.status === "fulfilled") {
      setOverlap(oRes.value.data.pairs ?? []);
      setWarnings(oRes.value.data.warnings ?? []);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    resolveClient().then(id => { if (id) fetchAll(id); else setLoading(false); });
  }, [resolveClient, fetchAll]);

  async function handleDelete(holdingId: number) {
    if (!clientId) return;
    setDeletingId(holdingId);
    try { await api.delete(`/holdings/${clientId}/${holdingId}`); setHoldings(prev => prev.filter(h => h.id !== holdingId)); }
    catch { } finally { setDeletingId(null); }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files?.length || !clientId) return;
    setUploading(true); setUploadError(null); setUploadPreview(null); setUploadDone(false);
    const form = new FormData();
    Array.from(files).forEach(f => form.append("files", f));
    try {
      const { data } = await api.post(`/holdings/${clientId}/upload`, form, { headers: { "Content-Type": "multipart/form-data" } });
      setUploadPreview({ preview: data.preview, message: data.message, raw: data });
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setUploadError(typeof detail === "string" ? detail : "Upload failed. Check the file format.");
    } finally { setUploading(false); if (fileRef.current) fileRef.current.value = ""; }
  }

  async function handleConfirm() {
    if (!clientId || !uploadPreview) return;
    setConfirming(true);
    try {
      await api.post(`/holdings/${clientId}/upload/confirm`, { result: uploadPreview.preview });
      setUploadDone(true); setUploadPreview(null); fetchAll(clientId);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setUploadError(typeof detail === "string" ? detail : "Confirm failed. Please try again.");
    } finally { setConfirming(false); }
  }

  const gainPositive = (summary?.absolute_gain ?? 0) >= 0;

  if (loading) return (<div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 256 }}><Spinner size={28} /></div>);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 500, margin: 0 }}>Holdings</h1>
          <p style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 4 }}>
            {client ? `${client.name} · ${holdings.length} fund${holdings.length !== 1 ? "s" : ""}` : ""}
          </p>
        </div>
        <button className="btn-secondary" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }} onClick={() => fileRef.current?.click()}>
          <IconUpload size={14} /> Upload statement
        </button>
        <input ref={fileRef} type="file" multiple accept=".pdf,.xlsx,.xls,.csv" style={{ display: "none" }} onChange={handleUpload} />
      </div>

      {summary && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
          {[
            { label: "Invested",      val: formatINR(summary.total_invested), colour: undefined, prefix: "" },
            { label: "Current value", val: formatINR(summary.total_current),  colour: undefined, prefix: "" },
            { label: "Absolute gain", val: formatINR(Math.abs(summary.absolute_gain)),
              colour: gainPositive ? "var(--color-positive)" : "var(--color-negative)", prefix: gainPositive ? "+" : "-" },
            { label: "Overall gain",  val: formatPct(summary.gain_percentage),
              colour: gainPositive ? "var(--color-positive)" : "var(--color-negative)", prefix: "" },
            { label: "Blended XIRR",  val: summary.blended_xirr != null ? `${summary.blended_xirr.toFixed(1)}%` : "—", colour: undefined, prefix: "" },
            { label: "Blended CAGR",  val: summary.blended_cagr != null ? `${summary.blended_cagr.toFixed(1)}%` : "—", colour: undefined, prefix: "" },
          ].map(({ label, val, colour, prefix }) => (
            <Card key={label}>
              <p style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 4 }}>{label}</p>
              <p style={{ fontSize: 17, fontWeight: 500, color: colour ?? "var(--color-text-primary)" }}>{prefix}{val}</p>
            </Card>
          ))}
        </div>
      )}

      {uploading && <Card style={{ display: "flex", alignItems: "center", gap: 10 }}><Spinner size={16} /><span style={{ fontSize: 13 }}>Parsing statement…</span></Card>}

      {uploadError && (
        <div style={{ background: "var(--color-negative-light)", border: "0.5px solid var(--color-negative)", borderRadius: 10, padding: "12px 16px", fontSize: 12, color: "var(--color-negative)", display: "flex", alignItems: "center", gap: 8 }}>
          <IconAlertTriangle size={14} /> {uploadError}
        </div>
      )}

      {uploadDone && (
        <div style={{ background: "#F0FDF4", border: "0.5px solid #86efac", borderRadius: 10, padding: "12px 16px", fontSize: 12, color: "#166534", display: "flex", alignItems: "center", gap: 8 }}>
          <IconCheck size={14} /> Statement imported successfully. Holdings updated.
        </div>
      )}

      {uploadPreview && (
        <Card>
          <SectionHeader icon={<IconUpload size={15} />} title="Statement preview — review before saving" />
          <div style={{ background: "var(--color-accent-light)", borderRadius: 8, padding: "12px 14px", marginBottom: 14, fontSize: 12, color: "var(--color-accent-dark)" }}>{uploadPreview.message}</div>
          <pre style={{ fontSize: 11, color: "var(--color-text-muted)", background: "#F8FAFB", borderRadius: 8, padding: 12, overflow: "auto", maxHeight: 200 }}>{JSON.stringify(uploadPreview.preview, null, 2)}</pre>
          <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
            <button className="btn-primary" disabled={confirming} onClick={handleConfirm} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {confirming ? <Spinner size={14} /> : <IconCheck size={14} />}{confirming ? "Saving…" : "Confirm & save"}
            </button>
            <button className="btn-secondary" onClick={() => setUploadPreview(null)} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <IconX size={14} /> Discard
            </button>
          </div>
        </Card>
      )}

      <Card>
        <SectionHeader icon={<IconBriefcase size={15} />} title={`Holdings (${holdings.length})`}
          action={clientId ? (
            <button onClick={() => fetchAll(clientId)} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-text-muted)", display: "flex", alignItems: "center", gap: 4, fontSize: 11 }}>
              <IconRefresh size={12} /> Refresh
            </button>
          ) : null}
        />
        {holdings.length === 0 ? (
          <EmptyState icon={<IconBriefcase />} title="No holdings yet" description="Upload a CAS statement or add holdings manually."
            action={<button className="btn-primary" onClick={() => fileRef.current?.click()} style={{ display: "flex", alignItems: "center", gap: 6 }}><IconUpload size={14} /> Upload statement</button>} />
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 80px 80px 100px 110px 70px 36px", gap: 8, padding: "6px 0", borderBottom: "0.5px solid var(--color-border)", marginBottom: 4 }}>
              {["Fund", "Units", "Avg NAV", "Invested", "Current", "CAGR", ""].map(h => (
                <span key={h} style={{ fontSize: 10, color: "var(--color-text-muted)", fontWeight: 500 }}>{h}</span>
              ))}
            </div>
            {holdings.map(h => {
              const gain = h.current_value - h.invested_amount;
              const gainPos = gain >= 0;
              return (
                <div key={h.id} style={{ display: "grid", gridTemplateColumns: "1fr 80px 80px 100px 110px 70px 36px", gap: 8, padding: "10px 0", borderBottom: "0.5px solid var(--color-border)", alignItems: "center" }}>
                  <div style={{ minWidth: 0 }}>
                    <p style={{ fontSize: 12, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{h.scheme_name}</p>
                    <p style={{ fontSize: 10, color: "var(--color-text-muted)", marginTop: 2 }}>Code: {h.scheme_code}</p>
                  </div>
                  <span style={{ fontSize: 12 }}>{h.units.toFixed(3)}</span>
                  <span style={{ fontSize: 12 }}>₹{h.avg_nav.toFixed(2)}</span>
                  <span style={{ fontSize: 12 }}>{formatINR(h.invested_amount)}</span>
                  <div>
                    <p style={{ fontSize: 12, fontWeight: 500 }}>{formatINR(h.current_value)}</p>
                    <p style={{ fontSize: 10, color: gainPos ? "var(--color-positive)" : "var(--color-negative)" }}>{gainPos ? "+" : "-"}{formatINR(Math.abs(gain))}</p>
                  </div>
                  <span style={{ fontSize: 12, fontWeight: 500, color: (h.cagr ?? 0) >= 0 ? "var(--color-positive)" : "var(--color-negative)" }}>
                    {h.cagr != null ? `${h.cagr.toFixed(1)}%` : "—"}
                  </span>
                  <button onClick={() => handleDelete(h.id)} disabled={deletingId === h.id}
                    style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-text-muted)", padding: 4, display: "flex", alignItems: "center" }}>
                    {deletingId === h.id ? <Spinner size={14} /> : <IconTrash size={14} />}
                  </button>
                </div>
              );
            })}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 80px 80px 100px 110px 70px 36px", gap: 8, padding: "10px 0 0", marginTop: 4 }}>
              <span style={{ fontSize: 11, color: "var(--color-text-muted)", fontWeight: 500 }}>Total</span>
              <span /><span />
              <span style={{ fontSize: 12, fontWeight: 500 }}>{formatINR(holdings.reduce((s, h) => s + h.invested_amount, 0))}</span>
              <span style={{ fontSize: 12, fontWeight: 500 }}>{formatINR(holdings.reduce((s, h) => s + h.current_value, 0))}</span>
              <span /><span />
            </div>
          </>
        )}
      </Card>

      <Card>
        <SectionHeader icon={<IconChartDots size={15} />} title="Fund overlap" />
        {warnings.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            {warnings.map((w, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "#92400E", background: "#FEF9EC", borderRadius: 6, padding: "5px 10px", marginBottom: 4 }}>
                <IconAlertTriangle size={12} /> {w}
              </div>
            ))}
          </div>
        )}
        {overlap.length === 0 ? (
          <EmptyState icon={<IconChartDots />} title="Not enough funds for overlap analysis" description="Overlap analysis requires at least 2 holdings." />
        ) : (
          <div>
            {overlap.map((pair, i) => {
              const col = overlapColour(pair.warning_level);
              return (
                <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 0", borderBottom: "0.5px solid var(--color-border)" }}>
                  <p style={{ fontSize: 12, flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {pair.fund_a_name} <span style={{ color: "var(--color-text-muted)" }}>×</span> {pair.fund_b_name}
                  </p>
                  <span style={{ fontSize: 12, fontWeight: 500, background: col.bg, color: col.text, padding: "2px 10px", borderRadius: 20, flexShrink: 0, marginLeft: 12 }}>
                    {pair.overlap_pct.toFixed(1)}%
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}
