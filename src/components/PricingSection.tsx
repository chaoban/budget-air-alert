import { Link } from "react-router";
import { ArrowRight, CalendarClock, Check, CreditCard, Route, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { FadeIn } from "@/components/FadeIn";
import { PLANS, formatTwd } from "@/lib/flightApi";
import { MONTHLY_PRICE_TWD } from "@/lib/pricing";

const included = [
  "每 30 分鐘查一次下個月來回最低票價",
  "低於或等於你的目標價就寄 email 通知，附訂購連結",
  "目標價隨時可以調整",
];

const terms = [
  {
    icon: Route,
    title: "計價方式",
    body: "依航線計費：每條航線各自訂閱、各自扣款，可同時訂閱多條。",
  },
  {
    icon: CreditCard,
    title: "付款方式",
    body: "信用卡付款，由綠界科技 ECPay 處理（信用卡定期定額）。本站不經手、不儲存你的信用卡資料。",
  },
  {
    icon: CalendarClock,
    title: "扣款週期",
    body: "付款完成即開始服務，之後每月自動扣款續訂；每期服務到下個月同一日 23:59（台北時間）。",
  },
  {
    icon: XCircle,
    title: "取消方式",
    body: "登入後在儀表板按「取消訂閱」，之後不再扣款；本期已付費的通知服務持續到本期結束日。",
  },
];

export function PricingSection() {
  return (
    <section id="pricing" className="mx-auto max-w-6xl scroll-mt-20 px-5 pb-24">
      <FadeIn className="mx-auto max-w-2xl text-center">
        <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">收費方案</h2>
        <p className="mt-4 text-muted-foreground">Pricing — 單一月費，依航線計價，新台幣收費。</p>
      </FadeIn>

      <FadeIn delay={100}>
        <div className="mx-auto mt-12 grid max-w-5xl overflow-hidden rounded-3xl border bg-card shadow-card md:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          {/* Price */}
          <div className="flex flex-col border-b bg-aura p-8 md:border-b-0 md:border-r">
            <p className="text-sm font-medium text-sepia">月訂閱 · Monthly plan</p>
            <p className="mt-4 flex items-baseline gap-1.5">
              <span className="text-5xl font-semibold tracking-tight text-foreground">
                {formatTwd(MONTHLY_PRICE_TWD)}
              </span>
              <span className="text-base text-muted-foreground">/ 月</span>
            </p>
            <p className="mt-1 text-sm font-medium text-foreground">每條航線</p>

            <div className="mt-5 flex flex-wrap gap-2">
              {PLANS.map((p) => (
                <span
                  key={p.planName}
                  className="rounded-full border border-primary/30 bg-background/70 px-3 py-1 text-xs font-medium text-foreground"
                >
                  {p.label}
                </span>
              ))}
            </div>

            <ul className="mt-6 space-y-2.5 text-sm text-muted-foreground">
              {included.map((item) => (
                <li key={item} className="flex gap-2">
                  <Check className="mt-0.5 size-4 shrink-0 text-primary" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>

            <div className="mt-auto pt-8">
              <Button asChild size="lg" className="h-12 w-full text-base shadow-glow">
                <Link to="/sign-up">
                  註冊並訂閱 <ArrowRight className="size-4" />
                </Link>
              </Button>
            </div>
          </div>

          {/* Billing terms */}
          <dl className="grid gap-px bg-border sm:grid-cols-2">
            {terms.map(({ icon: Icon, title, body }) => (
              <div key={title} className="bg-card p-7">
                <dt className="flex items-center gap-2.5 font-semibold text-foreground">
                  <span className="flex size-8 items-center justify-center rounded-full bg-accent text-primary">
                    <Icon className="size-4" />
                  </span>
                  {title}
                </dt>
                <dd className="mt-3 text-sm leading-relaxed text-muted-foreground">{body}</dd>
              </div>
            ))}
          </dl>
        </div>
      </FadeIn>
    </section>
  );
}
