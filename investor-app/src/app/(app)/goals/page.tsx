"use client";
import { IconHourglass } from "@tabler/icons-react";
export default function GoalsPage() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 256, gap: 12, color: 'var(--color-text-muted)' }}>
      <IconHourglass size={32} style={{ color: 'var(--color-accent)', opacity: 0.4 }} />
      <p style={{ fontSize: 13, fontWeight: 500 }}>Goals — coming next</p>
    </div>
  );
}
