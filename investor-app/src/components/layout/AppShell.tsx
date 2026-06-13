/**
 * components/layout/AppShell.tsx
 * Dark top nav + auth guard + mobile bottom tab bar.
 * Nav: Dashboard, Goals, Holdings, Discover, Chat, Reports
 */
"use client";
import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { IconLayoutDashboard, IconTarget, IconBriefcase, IconSearch, IconMessage, IconFileText, IconUserCircle, IconChevronDown, IconLogout } from "@tabler/icons-react";
import { getUser, logout, TokenPayload } from "@/lib/auth";
import { Spinner } from "@/components/ui";
import { clsx } from "clsx";

const NAV_LINKS = [
  { href: "/dashboard", label: "Dashboard", icon: IconLayoutDashboard },
  { href: "/goals",     label: "Goals",     icon: IconTarget },
  { href: "/holdings",  label: "Holdings",  icon: IconBriefcase },
  { href: "/discover",  label: "Discover",  icon: IconSearch },
  { href: "/chat",      label: "Chat",      icon: IconMessage },
  { href: "/reports",   label: "Reports",   icon: IconFileText },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const router   = useRouter();
  const pathname = usePathname();
  const [user,     setUser]     = useState<TokenPayload | null>(null);
  const [checking, setChecking] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const u = getUser();
    if (!u) { router.replace("/login"); }
    else { setUser(u); setChecking(false); }
  }, [router]);

  if (checking) return (
    <div style={{ display: "flex", height: "100vh", alignItems: "center", justifyContent: "center", background: "var(--color-bg)" }}>
      <Spinner size={28} />
    </div>
  );

  const firstName = user?.sub?.split("@")[0] ?? "You";

  return (
    <div style={{ minHeight: "100vh", background: "var(--color-bg)", display: "flex", flexDirection: "column" }}>
      <nav style={{ position: "fixed", top: 0, left: 0, right: 0, zIndex: 50, background: "#1C1C28", height: 52, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 24px" }}>
        <Link href="/dashboard" style={{ fontSize: 15, fontWeight: 500, color: "white", textDecoration: "none", letterSpacing: "-0.3px" }}>
          mf<span style={{ color: "#0891B2" }}>advisory</span>
        </Link>
        <div style={{ display: "flex", alignItems: "stretch", height: "100%" }}>
          {NAV_LINKS.map(({ href, label, icon: Icon }) => {
            const active = pathname.startsWith(href);
            return (
              <Link key={href} href={href} style={{ display: "flex", alignItems: "center", gap: 6, padding: "0 12px", fontSize: 12, textDecoration: "none", height: "100%", color: active ? "#fff" : "#777", borderBottom: active ? "2px solid #0891B2" : "2px solid transparent", transition: "color 0.15s" }}>
                <Icon size={14} />{label}
              </Link>
            );
          })}
        </div>
        <div style={{ position: "relative" }}>
          <button onClick={() => setMenuOpen(o => !o)} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "#ccc", background: "rgba(255,255,255,0.08)", border: "none", padding: "5px 12px", borderRadius: 20, cursor: "pointer" }}>
            <IconUserCircle size={14} /><span style={{ textTransform: "capitalize" }}>{firstName}</span><IconChevronDown size={12} />
          </button>
          {menuOpen && (
            <div style={{ position: "absolute", right: 0, top: 40, background: "var(--color-surface)", border: "0.5px solid var(--color-border)", borderRadius: 12, boxShadow: "0 1px 3px rgba(0,0,0,0.06)", width: 176, padding: "4px 0", zIndex: 50 }}>
              <button onClick={logout} style={{ display: "flex", alignItems: "center", gap: 8, width: "100%", padding: "10px 16px", fontSize: 11, background: "none", border: "none", cursor: "pointer", color: "var(--color-text-primary)" }}>
                <IconLogout size={14} style={{ color: "var(--color-text-muted)" }} />Sign out
              </button>
            </div>
          )}
        </div>
      </nav>
      <main style={{ flex: 1, marginTop: 52, marginBottom: 60 }}>
        <div style={{ maxWidth: 900, margin: "0 auto", padding: "24px 20px" }}>{children}</div>
      </main>
      <div style={{ position: "fixed", bottom: 0, left: 0, right: 0, background: "#1C1C28", height: 60, display: "flex", alignItems: "center", justifyContent: "space-around", borderTop: "0.5px solid var(--color-border)", zIndex: 50 }}>
        {NAV_LINKS.map(({ href, label, icon: Icon }) => {
          const active = pathname.startsWith(href);
          return (
            <Link key={href} href={href} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, fontSize: 10, textDecoration: "none", padding: "8px 8px", color: active ? "#0891B2" : "#666" }}>
              <Icon size={18} />{label}
            </Link>
          );
        })}
      </div>
    </div>
  );
}
