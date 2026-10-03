import type { ReactNode } from "react";
import { BrandMark } from "@/components/BrandMark";

/** Same paper-card layout as the sign-in page, for the password-recovery pages. */
export function AuthShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <div className="relative flex min-h-screen flex-col bg-aura">
      <div className="pointer-events-none absolute inset-0 bg-grid" aria-hidden />
      <header className="relative mx-auto flex h-16 w-full max-w-6xl items-center px-5">
        <BrandMark />
      </header>
      <main className="relative flex flex-1 items-center justify-center px-5 pb-20">
        <div className="animate-fade-up w-full max-w-md rounded-2xl border bg-card/80 p-8 shadow-card backdrop-blur">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">{subtitle}</p>
          <div className="mt-7">{children}</div>
        </div>
      </main>
    </div>
  );
}
