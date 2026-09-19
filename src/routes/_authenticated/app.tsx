import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { LogOut, Sparkles } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { BrandMark } from "@/components/BrandMark";
import { SiteFooter } from "@/components/SiteFooter";

export const Route = createFileRoute("/_authenticated/app")({
  head: () => ({
    meta: [
      { title: "儀表板 / Dashboard — Flight Price Notifier" },
      { name: "description", content: "Your Flight Price Notifier dashboard." },
      { property: "og:title", content: "儀表板 / Dashboard — Flight Price Notifier" },
      { property: "og:description", content: "Your Flight Price Notifier dashboard." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: AppShell,
});

function AppShell() {
  const { user } = Route.useRouteContext();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  async function handleSignOut() {
    await queryClient.cancelQueries();
    queryClient.clear();
    await supabase.auth.signOut();
    navigate({ to: "/auth", search: { mode: "signin" }, replace: true });
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 border-b border-border/60 bg-background/70 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
          <BrandMark />
          <div className="flex items-center gap-3">
            <span className="hidden text-sm text-muted-foreground sm:inline">{user.email}</span>
            <Button variant="outline" onClick={handleSignOut}>
              <LogOut className="size-4" /> Sign out / 登出
            </Button>
          </div>
        </div>
      </header>

      <main className="relative flex-1 bg-aura">
        <div className="pointer-events-none absolute inset-0 bg-grid" aria-hidden />
        <div className="relative mx-auto max-w-6xl px-5 py-16">
          <h1 className="animate-fade-up text-3xl font-semibold tracking-tight sm:text-4xl">
            Hi {user.email}
          </h1>
          <div
            className="animate-fade-up mt-8 max-w-2xl rounded-2xl border border-dashed border-primary/40 bg-card/70 p-8 shadow-card"
            style={{ animationDelay: "100ms" }}
          >
            <div className="mb-4 flex size-10 items-center justify-center rounded-xl bg-accent text-primary">
              <Sparkles className="size-5" />
            </div>
            <p className="text-lg font-medium leading-relaxed">
              你的航線追蹤儀表板即將上線 — 下一個里程碑會加上訂閱航線的功能。
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              Your dashboard is coming soon. Route-subscription will be added in the next milestone.
            </p>
          </div>
        </div>
      </main>

      <SiteFooter />
    </div>
  );
}
