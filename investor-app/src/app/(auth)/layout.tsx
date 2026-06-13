export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4"
         style={{ backgroundColor: 'var(--color-bg)' }}>
      {children}
    </div>
  );
}
