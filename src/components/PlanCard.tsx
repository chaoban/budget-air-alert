import { useEffect, useId, useState, type FormEvent } from "react";
import { BellRing, CheckCircle2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatTwd, type Plan, type Subscription } from "@/lib/flightApi";

interface PlanCardProps {
  plan: Plan;
  subscription?: Subscription | undefined;
  saving: boolean;
  disabled?: boolean | undefined;
  onSubmit: (targetPrice: number) => void;
}

export function PlanCard({ plan, subscription, saving, disabled, onSubmit }: PlanCardProps) {
  const inputId = useId();
  const [value, setValue] = useState(subscription ? String(subscription.target_price) : "");
  const [error, setError] = useState<string | null>(null);
  const subscribed = Boolean(subscription);

  // Keep the field in sync when the saved target changes (initial load / after an update).
  useEffect(() => {
    if (subscription) setValue(String(subscription.target_price));
  }, [subscription?.target_price]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const n = Number(value.replace(/[,\s]/g, ""));
    if (!Number.isFinite(n) || n <= 0 || n > 1_000_000) {
      setError("請輸入 1 ~ 1,000,000 之間的台幣金額");
      return;
    }
    setError(null);
    onSubmit(Math.round(n));
  }

  return (
    <div
      className={`relative flex h-full flex-col rounded-2xl border bg-card p-7 shadow-card transition-colors duration-300 ${
        subscribed ? "border-primary/50" : "hover:border-primary/40"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-2xl font-bold">{plan.label}</h3>
          <p className="mt-1 text-sm italic text-sepia">
            {plan.labelEn} · {plan.route}
          </p>
        </div>
        {subscribed && (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-primary px-3 py-1 text-xs font-semibold text-primary-foreground">
            <CheckCircle2 className="size-3.5" /> 已訂閱
          </span>
        )}
      </div>

      {subscribed ? (
        <p className="mt-5 text-sm leading-relaxed text-muted-foreground">
          目前目標價{" "}
          <span className="text-base font-semibold text-foreground">
            {formatTwd(subscription!.target_price)}
          </span>
          。下個月來回最低價一旦小於或等於這個金額，就寄信通知你。
        </p>
      ) : (
        <p className="mt-5 text-sm leading-relaxed text-muted-foreground">
          設定你願意付的來回票價（台幣），每 30 分鐘查一次下個月最低價，達標就寄信通知你。
        </p>
      )}

      <form onSubmit={handleSubmit} className="mt-auto pt-6" noValidate>
        <Label htmlFor={inputId} className="text-xs text-muted-foreground">
          目標價（TWD）· 參考：近期最低約 {formatTwd(plan.referencePrice)}
        </Label>
        <div className="mt-2 flex gap-2">
          <div className="relative flex-1">
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
              NT$
            </span>
            <Input
              id={inputId}
              inputMode="numeric"
              autoComplete="off"
              placeholder={`例如 ${Math.ceil((plan.referencePrice * 1.1) / 100) * 100}`}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              disabled={saving || disabled}
              aria-invalid={Boolean(error)}
              className="bg-background/60 pl-11"
            />
          </div>
          <Button type="submit" disabled={saving || disabled || !value.trim()}>
            {saving ? <Loader2 className="size-4 animate-spin" /> : <BellRing className="size-4" />}
            {subscribed ? "更新目標價" : "開始追蹤"}
          </Button>
        </div>
        {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
      </form>
    </div>
  );
}
