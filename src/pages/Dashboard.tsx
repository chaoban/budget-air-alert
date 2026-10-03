import { useNavigate, useRouteLoaderData } from "react-router";
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
  formatTwd,
  listSubscriptions,
  saveSubscription,
  type Subscription,
} from "@/lib/flightApi";

export function Dashboard() {
  usePageMeta({
    title: "儀表板 / Dashboard — Flight Price Notifier",
    description: "Your Flight Price Notifier dashboard.",
  });
  const { user } = useRouteLoaderData("authenticated") as { user: User };
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // Email is the join key across Supabase auth and the DynamoDB subscriptions table.
  const email = (user.email ?? "").toLowerCase();
  const subscriptionsKey = ["subscriptions", email] as const;

  const subscriptionsQuery = useQuery({
    queryKey: subscriptionsKey,
    queryFn: () => listSubscriptions(email),
    enabled: Boolean(email),
  });

  const saveMutation = useMutation({
    mutationFn: saveSubscription,
    onSuccess: (saved) => {
      queryClient.setQueryData<Subscription[]>(subscriptionsKey, (prev = []) => [
        ...prev.filter((s) => s.route !== saved.route),
        saved,
      ]);
      const plan = PLANS.find((p) => p.route === saved.route);
      toast.success(`${plan?.label ?? saved.route} 追蹤中`, {
        description: `目標價 ${formatTwd(saved.target_price)}，達標就寄信給你。`,
      });
    },
    onError: (err: Error) => toast.error("儲存失敗", { description: err.message }),
  });

  async function handleSignOut() {
    await queryClient.cancelQueries();
    queryClient.clear();
    await supabase.auth.signOut();
    navigate("/sign-in", { replace: true });
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
          <p
            className="animate-fade-up mt-3 max-w-2xl text-muted-foreground"
            style={{ animationDelay: "60ms" }}
          >
            選一條航線、設定目標價。下個月的來回最低價一旦達標，我們就寄信到{" "}
            <span className="font-medium text-foreground">{email}</span>。
          </p>

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
            className="animate-fade-up mt-8 grid gap-6 md:grid-cols-2"
            style={{ animationDelay: "100ms" }}
          >
            {PLANS.map((plan) => (
              <PlanCard
                key={plan.planName}
                plan={plan}
                subscription={subscriptionsQuery.data?.find((s) => s.route === plan.route)}
                saving={
                  saveMutation.isPending && saveMutation.variables?.plan_name === plan.planName
                }
                disabled={subscriptionsQuery.isPending}
                onSubmit={(targetPrice) =>
                  saveMutation.mutate({
                    email,
                    plan_name: plan.planName,
                    target_price: targetPrice,
                  })
                }
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
