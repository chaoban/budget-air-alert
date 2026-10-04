import { SaisaiLogo } from "@/components/SaisaiLogo";

export function SiteFooter() {
  return (
    <footer className="border-t border-border/60">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-5 py-10 sm:flex-row sm:items-end">
        <div className="flex flex-col items-center gap-2.5 sm:items-start">
          <SaisaiLogo className="h-6" />
          <span className="text-xs text-muted-foreground">© 2026 SAISAI. All rights reserved.</span>
        </div>
        <span className="text-sm text-muted-foreground">
          Flight Price Notifier · 機票降價通知 · 台北出發
        </span>
      </div>
    </footer>
  );
}
