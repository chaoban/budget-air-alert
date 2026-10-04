import { useEffect, useId, useState, type FormEvent, type ReactNode } from "react";
import {
  BellRing,
  CheckCircle2,
  Clock,
  CreditCard,
  Loader2,
  RotateCcw,
  XCircle,
} from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatTwd, type Plan, type Subscription, type SubscriptionStatus } from "@/lib/flightApi";

interface PlanCardProps {
  plan: Plan;
  subscription?: Subscription | undefined;
  monthlyPrice: number | null;
  saving: boolean;
  cancelling: boolean;
  disabled?: boolean | undefined;
  /** New subscription / pay / re-subscribe, or an in-place target update when already paid. */
  onSubmit: (targetPrice: number) => void;
  onCancel: () => void;
}

const BADGE: Record<SubscriptionStatus, { label: string; className: string; icon: ReactNode }> = {
  active: {
    label: "已訂閱",
    className: "bg-primary text-primary-foreground",
    icon: <CheckCircle2 className="size-3.5" />,
  },
  pending_payment: {
    label: "尚未付款",
    className: "bg-amber-100 text-amber-900 ring-1 ring-amber-300",
    icon: <Clock className="size-3.5" />,
  },
  cancelled: {
    label: "已取消",
    className: "bg-secondary text-secondary-foreground ring-1 ring-border",
    icon: <XCircle className="size-3.5" />,
  },
  expired: {
    label: "已結束",
    className: "bg-muted text-muted-foreground ring-1 ring-border",
    icon: <XCircle className="size-3.5" />,
  },
};

export function PlanCard({
  plan,
  subscription,
  monthlyPrice,
  saving,
  cancelling,
  disabled,
  onSubmit,
  onCancel,
}: PlanCardProps) {
  const inputId = useId();
  const [value, setValue] = useState(subscription ? String(subscription.target_price) : "");
  const [error, setError] = useState<string | null>(null);
  const status = subscription?.subscription_status;
  const paidThrough = status === "active" || status === "cancelled";
  const price = monthlyPrice ? `${formatTwd(monthlyPrice)}/月` : "月費";
  const until = subscription?.current_period_end_date;

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

  let description: ReactNode;
  let action: { label: string; icon: ReactNode };
  switch (status) {
    case "active":
      description = (
        <>
          目標價 <Strong>{formatTwd(subscription!.target_price)}</Strong>
          。下個月來回最低價一旦小於或等於這個金額，就寄信通知你。
          {until && <span className="mt-1 block">本期有效至 {until}，每月自動續訂。</span>}
        </>
      );
      action = { label: "更新目標價", icon: <BellRing className="size-4" /> };
      break;
    case "cancelled":
      description = (
        <>
          已取消續訂，不會再扣款。本期已付費，降價通知持續到 <Strong>{until ?? "本期結束"}</Strong>
          ；期間內仍可調整目標價。
        </>
      );
      action = { label: "更新目標價", icon: <BellRing className="size-4" /> };
      break;
    case "pending_payment":
      description = (
        <>
          目標價 <Strong>{formatTwd(subscription!.target_price)}</Strong>
          。尚未付款，付款後才會開始寄降價通知。
        </>
      );
      action = { label: "前往付款", icon: <CreditCard className="size-4" /> };
      break;
    case "expired":
      description = <>這個訂閱已經結束，不會再寄通知。重新訂閱並付款後恢復。</>;
      action = { label: "重新訂閱", icon: <RotateCcw className="size-4" /> };
      break;
    default:
      description = (
        <>設定你願意付的來回票價（台幣），每 30 分鐘查一次下個月最低價，達標就寄信通知你。</>
      );
      action = { label: "訂閱並付款", icon: <CreditCard className="size-4" /> };
  }

  return (
    <div
      className={`relative flex h-full flex-col rounded-2xl border bg-card p-7 shadow-card transition-colors duration-300 ${
        status === "active" ? "border-primary/50" : "hover:border-primary/40"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-2xl font-bold">{plan.label}</h3>
          <p className="mt-1 text-sm italic text-sepia">
            {plan.labelEn} · {plan.route}
          </p>
        </div>
        {status && (
          <span
            className={`inline-flex shrink-0 items-center gap-1 rounded-full px-3 py-1 text-xs font-semibold ${BADGE[status].className}`}
          >
            {BADGE[status].icon} {BADGE[status].label}
          </span>
        )}
      </div>

      <p className="mt-5 text-sm leading-relaxed text-muted-foreground">{description}</p>

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
            {saving ? <Loader2 className="size-4 animate-spin" /> : action.icon}
            {action.label}
          </Button>
        </div>
        {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
        {!paidThrough && (
          <p className="mt-2 text-xs text-muted-foreground">
            {price}，綠界信用卡定期定額，每月自動扣款，可隨時取消。
          </p>
        )}
      </form>

      {status === "active" && (
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <button
              type="button"
              disabled={cancelling || disabled}
              className="mt-4 self-start text-xs text-muted-foreground underline-offset-4 hover:text-destructive hover:underline disabled:opacity-50"
            >
              {cancelling ? "取消中…" : "取消訂閱"}
            </button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>取消 {plan.label} 的訂閱？</AlertDialogTitle>
              <AlertDialogDescription>
                之後不會再自動扣款。本期已付費，降價通知會持續到 {until ?? "本期結束"}。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>先不要</AlertDialogCancel>
              <AlertDialogAction onClick={onCancel}>確定取消</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </div>
  );
}

function Strong({ children }: { children: ReactNode }) {
  return <span className="font-semibold text-foreground">{children}</span>;
}
