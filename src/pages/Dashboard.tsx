import { useEffect, useState } from "react";
import { useNavigate, useRouteLoaderData, useSearchParams } from "react-router";
import type { User } from "@supabase/supabase-js";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, LogOut } from "lucide-react";
import { toast } from "sonner";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { BrandMark } from "@/components/BrandMark";
import { PlanCard } from "@/components/PlanCard";
import { SiteFooter } from "@/components/SiteFooter";
import { usePageMeta } from "@/hooks/usePageMeta";
import {
  PLANS,
  cancelSubscription,
  formatTwd,
  goToCheckout,
  listSubscriptions,
  saveSubscription,
  type Subscription,
  type SubscriptionList,
} from "@/lib/flightApi";

/** After ECPay sends the browser back, poll until the server-to-server ReturnURL activates the row. */
const ACTIVATION_POLL_MS = 3000;
const ACTIVATION_POLL_LIMIT_MS = 90_000;

export function Dashboard() {
  usePageMeta({
    title: "儀表板 / Dashboard — Flight Price Notifier",
    description: "Your Flight Price Notifier dashboard.",
  });
  const { user } = useRouteLoaderData("authenticated") as { user: User };
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  // The API reads the subscriber's email from the verified Supabase session token.
  const email = (user.email ?? "").toLowerCase();
  const subscriptionsKey = ["subscriptions", email] as const;

  // Route we are waiting on after a successful checkout, plus when we started waiting.
  const [awaiting, setAwaiting] = useState<{ route: string; since: number } | null>(null);

  const subscriptionsQuery = useQuery({
    queryKey: subscriptionsKey,
    queryFn: listSubscriptions,
    enabled: Boolean(email),
    refetchInterval: awaiting ? ACTIVATION_POLL_MS : false,
  });
  const subscriptions = subscriptionsQuery.data?.subscriptions;
  const monthlyPrice = subscriptionsQuery.data?.monthlyPrice ?? null;

  // Handle ECPay's OrderResultURL redirect: /app?purchase=success|failed&route=TPE-XXX
  useEffect(() => {
    const purchase = searchParams.get("purchase");
    if (!purchase) return;
    const route = searchParams.get("route") ?? "";
    const label = PLANS.find((p) => p.route === route)?.label ?? route;
    if (purchase === "success") {
      toast.success(`${label} 付款完成`, {
        description: "正在確認綠界扣款結果，通常幾秒內就會啟用。",
      });
      if (route) setAwaiting({ route, since: Date.now() });
    } else {
      toast.error(`${label} 付款未完成`, {
        description: "沒有扣款。可以再按一次「前往付款」重試。",
      });
    }
    const next = new URLSearchParams(searchParams);
    next.delete("purchase");
    next.delete("route");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  // Stop polling once the awaited route is active, or after the time limit.
  useEffect(() => {
    if (!awaiting) return;
    const row = subscriptions?.find((s) => s.route === awaiting.route);
    if (row?.subscription_status === "active") {
      const label = PLANS.find((p) => p.route === awaiting.route)?.label ?? awaiting.route;
      toast.success(`${label} 訂閱已啟用`, {
        description: "確認信已寄出，達標就會寄降價通知給你。",
      });
      setAwaiting(null);
    } else if (Date.now() - awaiting.since > ACTIVATION_POLL_LIMIT_MS) {
      toast.message("付款結果還在處理中", { description: "稍後重新整理頁面就會看到最新狀態。" });
      setAwaiting(null);
    }
  }, [awaiting, subscriptions]);

  function upsert(saved: Subscription) {
    queryClient.setQueryData<SubscriptionList>(subscriptionsKey, (prev) => ({
      monthlyPrice: prev?.monthlyPrice ?? null,
      subscriptions: [...(prev?.subscriptions ?? []).filter((s) => s.route !== saved.route), saved],
    }));
  }

  const saveMutation = useMutation({
    mutationFn: saveSubscription,
    onSuccess: (result) => {
      if (result.kind === "checkout") {
        // Leave the SPA for ECPay's cashier; it comes back via /ecpay-result → /app?purchase=…
        goToCheckout(result.html);
        return;
      }
      const saved = result.subscription;
      upsert(saved);
      const plan = PLANS.find((p) => p.route === saved.route);
      toast.success(`${plan?.label ?? saved.route} 目標價已更新`, {
        description: `目標價 ${formatTwd(saved.target_price)}，達標就寄信給你。`,
      });
    },
    onError: (err: Error) => toast.error("送出失敗", { description: err.message }),
  });

  const cancelMutation = useMutation({
    mutationFn: cancelSubscription,
    onSuccess: (saved, route) => {
      if (saved) upsert(saved);
      void queryClient.invalidateQueries({ queryKey: subscriptionsKey });
      const label = PLANS.find((p) => p.route === route)?.label ?? route;
      toast.success(`已取消 ${label} 的訂閱`, {
        description: saved?.current_period_end_date
          ? `不會再扣款，降價通知持續到 ${saved.current_period_end_date}。`
          : "不會再扣款。",
      });
    },
    onError: (err: Error) => toast.error("取消失敗", { description: err.message }),
  });

  async function handleSignOut() {
    await queryClient.cancelQueries();
    queryClient.clear();
    await supabase.auth.signOut();
    navigate("/sign-in", { replace: true });
  }

  const priceText = monthlyPrice ? `${formatTwd(monthlyPrice)}/月` : "月費";

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
          <p
            className="animate-fade-up mt-3 max-w-2xl text-muted-foreground"
            style={{ animationDelay: "60ms" }}
          >
            選一條航線、設定目標價，每條航線 {priceText}
            。付款後，下個月的來回最低價一旦達標，我們就寄信到{" "}
            <span className="font-medium text-foreground">{email}</span>。
          </p>

          {awaiting && (
            <div className="mt-6 flex max-w-2xl items-center gap-3 rounded-xl border border-primary/40 bg-card/80 px-5 py-4 text-sm">
              <Loader2 className="size-4 animate-spin text-primary" />
              <span>正在確認綠界付款結果…</span>
            </div>
          )}

          {subscriptionsQuery.isError && (
            <div className="mt-6 flex max-w-2xl items-center justify-between gap-4 rounded-xl border border-destructive/40 bg-card/80 px-5 py-4 text-sm">
              <span className="text-destructive">
                讀取訂閱狀態失敗：{(subscriptionsQuery.error as Error).message}
              </span>
              <Button variant="outline" size="sm" onClick={() => subscriptionsQuery.refetch()}>
                重試
              </Button>
            </div>
          )}

          <div
            className="animate-fade-up mt-8 grid gap-6 md:grid-cols-2 lg:grid-cols-3"
            style={{ animationDelay: "100ms" }}
          >
            {PLANS.map((plan) => (
              <PlanCard
                key={plan.planName}
                plan={plan}
                subscription={subscriptions?.find((s) => s.route === plan.route)}
                monthlyPrice={monthlyPrice}
                saving={
                  saveMutation.isPending && saveMutation.variables?.plan_name === plan.planName
                }
                cancelling={cancelMutation.isPending && cancelMutation.variables === plan.route}
                disabled={subscriptionsQuery.isPending}
                onSubmit={(targetPrice) =>
                  saveMutation.mutate({ plan_name: plan.planName, target_price: targetPrice })
                }
                onCancel={() => cancelMutation.mutate(plan.route)}
              />
            ))}
          </div>
          {subscriptionsQuery.isPending && (
            <p className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> 讀取訂閱狀態中…
            </p>
          )}
        </div>
      </main>

      <SiteFooter />
    </div>
  );
}
