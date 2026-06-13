/**
 * app/(app)/reports/page.tsx
 * Investor view: list reports + download. Generation is advisor-only.
 */
"use client";
import { useEffect, useState, useCallback } from "react";
import { IconFileText, IconDownload, IconRefresh, IconClock } from "@tabler/icons-react";
import api from "@/lib/api";
import { getUser } from "@/lib/auth";
import { Card, SectionHeader, Pill, Spinner, EmptyState } from "@/components/ui";
import type { Client } from "@/types";

interface Report {
  id: number; client_id: number; advisor_id: number | null; report_type: string;
  period: string; file_path: string | null; sent_at: string | null;
  approval_status: string; created_at: string;
}

function statusVariant(s: string): "success" | "warn" | "neutral" {
  if (s === "sent") return "success"; if (s === "approved") return "warn"; return "neutral";
}
function fmtDate(iso: string) { return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }); }

export default function ReportsPage() {
  const user = getUser();
  const [client,      setClient]      = useState<Client | null>(null);
  const [clientId,    setClientId]    = useState<number | null>(null);
  const [reports,     setReports]     = useState<Report[]>([]);
  const [loading,     setLoading]     = useState(true);
  const [downloading, setDownloading] = useState<number | null>(null);

  const resolveClient = useCallback(async () => {
    try {
      if (user?.role === "investor") { const { data } = await api.get("/clients/me"); setClient(data); setClientId(data.id); return data.id as number; }
      else { const { data } = await api.get("/clients/"); if (!data?.length) return null; const id = data[0].id as number; const cr = await api.get(`/clients/${id}`); setClient(cr.data); setClientId(id); return id; }
    } catch { return null; }
  }, [user?.role]);

  const fetchReports = useCallback(async (id: number) => {
    setLoading(true);
    try { const { data } = await api.get(`/reports/${id}/list`); setReports(data); }
    catch { setReports([]); } finally { setLoading(false); }
  }, []);

  useEffect(() => { resolveClient().then(id => { if (id) fetchReports(id); else setLoading(false); }); }, [resolveClient, fetchReports]);

  async function handleDownload(reportId: number) {
    setDownloading(reportId);
    try {
      const response = await api.get(`/reports/${reportId}/download`, { responseType: "blob" });
      const url = URL.createObjectURL(new Blob([response.data], { type: "text/markdown" }));
      const a = document.createElement("a"); a.href = url; a.download = `advisory_report_${reportId}.md`; a.click(); URL.revokeObjectURL(url);
    } catch { alert("Report file not available yet. Ask your advisor to generate it."); }
    finally { setDownloading(null); }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 500, margin: 0 }}>Reports</h1>
          <p style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 4 }}>{client ? `${client.name} \u00b7 Advisory reports` : ""}</p>
        </div>
        {clientId && <button onClick={() => fetchReports(clientId)} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-text-muted)", display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}><IconRefresh size={13} /> Refresh</button>}
      </div>

      <div style={{ background: "var(--color-accent-light)", border: "0.5px solid var(--color-accent)", borderRadius: 12, padding: "14px 16px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <p style={{ fontSize: 13, fontWeight: 500, color: "var(--color-accent-dark)", marginBottom: 2 }}>Want a portfolio review?</p>
          <p style={{ fontSize: 12, color: "var(--color-accent-dark)", opacity: 0.8 }}>Your advisor will generate and share a fresh report.</p>
        </div>
        <button className="btn-ghost" style={{ fontSize: 12, whiteSpace: "nowrap" }}>Request review</button>
      </div>

      <Card>
        <SectionHeader icon={<IconFileText size={15} />} title={`Reports${reports.length ? ` (${reports.length})` : ""}`} />
        {loading ? <div style={{ display: "flex", justifyContent: "center", padding: "2rem 0" }}><Spinner size={24} /></div>
        : reports.length === 0 ? <EmptyState icon={<IconFileText />} title="No reports yet" description="Your advisor will generate portfolio review reports and share them here." />
        : (
          <div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 100px 120px 90px 80px", gap: 8, padding: "6px 0", borderBottom: "0.5px solid var(--color-border)", marginBottom: 4 }}>
              {["Report", "Type", "Period", "Status", ""].map(h => <span key={h} style={{ fontSize: 10, color: "var(--color-text-muted)", fontWeight: 500 }}>{h}</span>)}
            </div>
            {reports.map(r => (
              <div key={r.id} style={{ display: "grid", gridTemplateColumns: "1fr 100px 120px 90px 80px", gap: 8, padding: "12px 0", borderBottom: "0.5px solid var(--color-border)", alignItems: "center" }}>
                <div>
                  <p style={{ fontSize: 12, fontWeight: 500 }}>Advisory report #{r.id}</p>
                  <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 2, fontSize: 10, color: "var(--color-text-muted)" }}>
                    <IconClock size={10} />{fmtDate(r.created_at)}{r.sent_at && ` \u00b7 Sent ${fmtDate(r.sent_at)}`}
                  </div>
                </div>
                <span style={{ fontSize: 11, color: "var(--color-text-muted)", textTransform: "capitalize" }}>{r.report_type.replace("_", " ")}</span>
                <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{r.period}</span>
                <Pill variant={statusVariant(r.approval_status)}>{r.approval_status}</Pill>
                <button onClick={() => handleDownload(r.id)} disabled={downloading === r.id || !r.file_path}
                  style={{ display: "flex", alignItems: "center", gap: 4, background: "none", border: "none", cursor: r.file_path ? "pointer" : "not-allowed", color: r.file_path ? "var(--color-accent)" : "var(--color-text-muted)", fontSize: 12, padding: 0, opacity: r.file_path ? 1 : 0.4 }}>
                  {downloading === r.id ? <Spinner size={13} /> : <IconDownload size={13} />}
                  {downloading === r.id ? "..." : "Download"}
                </button>
              </div>
            ))}
          </div>
        )}
      </Card>
      <div style={{ fontSize: 11, color: "var(--color-text-muted)", textAlign: "center" }}>Reports are generated by your advisor \u00b7 Download as Markdown</div>
    </div>
  );
}
