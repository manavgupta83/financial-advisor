/**
 * app/(app)/chat/page.tsx
 * Investor AI chat powered by Claude Haiku — grounded in client data.
 * No Phase 6 chat router exists — calls Anthropic API directly.
 * Read-only. Suggested questions on load.
 */
"use client";
import { useState, useCallback, useEffect, useRef } from "react";
import { IconSend, IconSparkles, IconUser, IconRobot, IconRefresh } from "@tabler/icons-react";
import api from "@/lib/api";
import { getUser } from "@/lib/auth";
import { Spinner, formatINR } from "@/components/ui";
import type { Client, Goal, Holding, PortfolioSummary } from "@/types";

interface Message { role: "user" | "assistant"; content: string; }

export default function ChatPage() {
  const user = getUser();
  const [client,   setClient]   = useState<Client | null>(null);
  const [goals,    setGoals]    = useState<Goal[]>([]);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [summary,  setSummary]  = useState<PortfolioSummary | null>(null);
  const [ctxReady, setCtxReady] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input,    setInput]    = useState("");
  const [streaming,setStreaming] = useState(false);
  const [error,    setError]    = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef  = useRef<HTMLTextAreaElement>(null);

  const loadContext = useCallback(async () => {
    try {
      let clientId: number; let clientData: Client;
      if (user?.role === "investor") {
        const { data } = await api.get("/clients/me"); clientData = data; clientId = data.id;
      } else {
        const { data } = await api.get("/clients/");
        if (!data?.length) return;
        clientId = data[0].id;
        const cr = await api.get(`/clients/${clientId}`); clientData = cr.data;
      }
      setClient(clientData);
      const [gRes, hRes, sRes] = await Promise.allSettled([
        api.get(`/goals/${clientId}`), api.get(`/holdings/${clientId}`), api.get(`/portfolio/${clientId}/summary`),
      ]);
      if (gRes.status === "fulfilled") setGoals(gRes.value.data);
      if (hRes.status === "fulfilled") {
        const seen = new Set<number>();
        setHoldings((hRes.value.data as Holding[]).filter(h => { if (seen.has(h.scheme_code)) return false; seen.add(h.scheme_code); return true; }));
      }
      if (sRes.status === "fulfilled") setSummary(sRes.value.data);
      setCtxReady(true);
    } catch { setCtxReady(true); }
  }, [user?.role]);

  useEffect(() => { loadContext(); }, [loadContext]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, streaming]);

  function buildSystemPrompt(): string {
    const lines = [
      "You are a helpful mutual fund investment assistant for an Indian investor.",
      "You can only see their data listed below — do not make up numbers.",
      "Be concise, friendly, and use Indian financial context (\u20b9, SIP, XIRR, CAGR, SEBI).",
      "You are READ-ONLY. You cannot change any plans, goals, or holdings.",
      "If the investor wants to change something, tell them to speak to their advisor.", "",
    ];
    if (client) { lines.push(`INVESTOR: ${client.name}, Age ${client.age}, Income \u20b9${client.annual_income.toLocaleString("en-IN")}/yr`); lines.push(`Risk profile: ${client.risk_profile ?? "Not assessed"}`); }
    if (summary) { lines.push(`\nPORTFOLIO: Invested \u20b9${summary.total_invested.toLocaleString("en-IN")}, Current \u20b9${summary.total_current.toLocaleString("en-IN")}, Gain ${summary.gain_percentage.toFixed(1)}%`); if (summary.blended_xirr != null) lines.push(`XIRR: ${summary.blended_xirr.toFixed(1)}%`); }
    if (goals.length > 0) { lines.push("\nGOALS:"); goals.forEach(g => lines.push(`- ${g.goal_name}: target \u20b9${g.target_amount.toLocaleString("en-IN")} by ${g.target_year}, SIP \u20b9${g.monthly_sip.toLocaleString("en-IN")}/mo`)); }
    if (holdings.length > 0) { lines.push("\nHOLDINGS:"); holdings.forEach(h => lines.push(`- ${h.scheme_name}: \u20b9${h.invested_amount.toLocaleString("en-IN")} invested, current \u20b9${h.current_value.toLocaleString("en-IN")}${h.cagr != null ? `, CAGR ${h.cagr.toFixed(1)}%` : ""}`)); }
    return lines.join("\n");
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || streaming) return;
    const userMsg: Message = { role: "user", content: text };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages); setInput(""); setError(null); setStreaming(true);
    setMessages(prev => [...prev, { role: "assistant", content: "" }]);
    try {
      const response = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: "claude-haiku-4-5-20251001", max_tokens: 1000,
          system: buildSystemPrompt(),
          messages: newMessages.map(m => ({ role: m.role, content: m.content })),
          stream: true,
        }),
      });
      if (!response.ok) { const err = await response.json(); throw new Error(err.error?.message ?? "API error"); }
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let assistantText = "";
      while (reader) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value);
        const lines = chunk.split("\n").filter(l => l.startsWith("data: "));
        for (const line of lines) {
          const data = line.slice(6);
          if (data === "[DONE]") break;
          try { const parsed = JSON.parse(data); const delta = parsed.delta?.text ?? ""; if (delta) { assistantText += delta; setMessages(prev => { const u = [...prev]; u[u.length - 1] = { role: "assistant", content: assistantText }; return u; }); } } catch { }
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setMessages(prev => prev.slice(0, -1));
    } finally { setStreaming(false); }
  }

  function handleKeyDown(e: React.KeyboardEvent) { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }
  function clearChat() { setMessages([]); setError(null); }

  const suggestions = ["How is my portfolio performing?", "Am I on track for my retirement goal?", "Which of my funds has the best CAGR?", "What does my sector allocation look like?"];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 120px)", gap: 0 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 500, margin: 0 }}>Chat</h1>
          <p style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 4 }}>Ask anything about your portfolio \u00b7 Read-only</p>
        </div>
        {messages.length > 0 && <button onClick={clearChat} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-text-muted)", display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}><IconRefresh size={13} /> Clear</button>}
      </div>

      {!ctxReady && <div style={{ display: "flex", alignItems: "center", justifyContent: "center", flex: 1 }}><Spinner size={24} /></div>}

      {ctxReady && (
        <>
          <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 12, paddingBottom: 16 }}>
            {messages.length === 0 && (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16, padding: "2rem 0" }}>
                <div style={{ width: 48, height: 48, borderRadius: 24, background: "var(--color-accent-light)", display: "flex", alignItems: "center", justifyContent: "center" }}><IconSparkles size={22} style={{ color: "var(--color-accent)" }} /></div>
                <div style={{ textAlign: "center" }}>
                  <p style={{ fontSize: 15, fontWeight: 500, marginBottom: 6 }}>Hi{client ? `, ${client.name.split(" ")[0]}` : ""}!</p>
                  <p style={{ fontSize: 13, color: "var(--color-text-muted)", maxWidth: 320 }}>Ask me anything about your portfolio, goals, or holdings.</p>
                </div>
                {summary && (
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, width: "100%", maxWidth: 400 }}>
                    {[{ label: "Portfolio", val: formatINR(summary.total_current) }, { label: "Gain", val: `${summary.gain_percentage >= 0 ? "+" : ""}${summary.gain_percentage.toFixed(1)}%` }, { label: "Goals", val: `${goals.length} active` }].map(({ label, val }) => (
                      <div key={label} style={{ background: "var(--color-surface)", border: "0.5px solid var(--color-border)", borderRadius: 10, padding: "10px 12px", textAlign: "center" }}>
                        <p style={{ fontSize: 10, color: "var(--color-text-muted)", marginBottom: 3 }}>{label}</p>
                        <p style={{ fontSize: 14, fontWeight: 500 }}>{val}</p>
                      </div>
                    ))}
                  </div>
                )}
                <div style={{ display: "flex", flexDirection: "column", gap: 8, width: "100%", maxWidth: 400 }}>
                  <p style={{ fontSize: 11, color: "var(--color-text-muted)", textAlign: "center" }}>Try asking</p>
                  {suggestions.map(s => (
                    <button key={s} onClick={() => { setInput(s); inputRef.current?.focus(); }}
                      style={{ background: "var(--color-surface)", border: "0.5px solid var(--color-border)", borderRadius: 8, padding: "9px 14px", fontSize: 12, color: "var(--color-text-primary)", cursor: "pointer", textAlign: "left" }}
                      onMouseEnter={e => (e.currentTarget.style.borderColor = "var(--color-accent)")}
                      onMouseLeave={e => (e.currentTarget.style.borderColor = "var(--color-border)")}>{s}</button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} style={{ display: "flex", gap: 10, alignItems: "flex-start", flexDirection: m.role === "user" ? "row-reverse" : "row" }}>
                <div style={{ width: 28, height: 28, borderRadius: 14, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", background: m.role === "user" ? "var(--color-accent)" : "var(--color-accent-light)" }}>
                  {m.role === "user" ? <IconUser size={14} style={{ color: "white" }} /> : <IconRobot size={14} style={{ color: "var(--color-accent)" }} />}
                </div>
                <div style={{ maxWidth: "75%", padding: "10px 14px", borderRadius: 12, fontSize: 13, lineHeight: 1.6, whiteSpace: "pre-wrap",
                  background: m.role === "user" ? "var(--color-accent)" : "var(--color-surface)",
                  color: m.role === "user" ? "white" : "var(--color-text-primary)",
                  border: m.role === "user" ? "none" : "0.5px solid var(--color-border)",
                  borderTopRightRadius: m.role === "user" ? 4 : 12, borderTopLeftRadius: m.role === "assistant" ? 4 : 12 }}>
                  {m.content}
                  {streaming && i === messages.length - 1 && m.role === "assistant" && m.content === "" && (
                    <span style={{ display: "inline-flex", gap: 3 }}>
                      {[0, 0.2, 0.4].map((d, j) => <span key={j} style={{ width: 4, height: 4, borderRadius: 2, background: "var(--color-text-muted)", display: "inline-block", animation: `pulse 1s ${d}s infinite` }} />)}
                    </span>
                  )}
                </div>
              </div>
            ))}
            {error && <div style={{ background: "var(--color-negative-light)", borderRadius: 8, padding: "10px 14px", fontSize: 12, color: "var(--color-negative)" }}>{error}</div>}
            <div ref={bottomRef} />
          </div>
          <div style={{ fontSize: 10, color: "var(--color-text-muted)", textAlign: "center", padding: "6px 0", borderTop: "0.5px solid var(--color-border)", marginBottom: 10 }}>
            Chat is read-only \u00b7 Preference changes go to your advisor for approval
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
            <textarea ref={inputRef} value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKeyDown}
              placeholder="Ask about your portfolio\u2026 (Enter to send, Shift+Enter for new line)" rows={2}
              style={{ flex: 1, resize: "none", border: "0.5px solid var(--color-border)", borderRadius: 10, padding: "10px 14px", fontSize: 13, fontFamily: "inherit", background: "var(--color-surface)", color: "var(--color-text-primary)", outline: "none", lineHeight: 1.5 }}
              onFocus={e => (e.currentTarget.style.borderColor = "var(--color-accent)")}
              onBlur={e => (e.currentTarget.style.borderColor = "var(--color-border)")} />
            <button onClick={handleSend} disabled={!input.trim() || streaming} className="btn-primary"
              style={{ padding: "10px 16px", display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
              {streaming ? <Spinner size={14} /> : <IconSend size={14} />} Send
            </button>
          </div>
        </>
      )}
      <style>{`@keyframes pulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 1; } }`}</style>
    </div>
  );
}
