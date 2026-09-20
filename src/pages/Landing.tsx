import { Link } from "react-router";
import { BellRing, Radar, XCircle, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SiteHeader } from "@/components/SiteHeader";
import { SiteFooter } from "@/components/SiteFooter";
import { FeatureCard } from "@/components/FeatureCard";
import { FadeIn } from "@/components/FadeIn";
import { usePageMeta } from "@/hooks/usePageMeta";

const features = [
  {
    icon: Radar,
    title: "盯緊熱門航線",
    subtitle: "Always-on route watching",
    body: "持續監控台北出發的熱門航線（東京、首爾），自動抓最低票價。",
  },
  {
    icon: BellRing,
    title: "達標自動通知",
    subtitle: "Target-price email alerts",
    body: "低於你設定的目標價，就寄 email 提醒你，附上立即訂購連結。",
  },
  {
    icon: XCircle,
    title: "隨時取消",
    subtitle: "Cancel anytime",
    body: "月訂閱制，不想用隨時停，沒有綁約。",
  },
];

export function Landing() {
  usePageMeta({
    title: "Flight Price Notifier — 機票降價通知",
    description:
      "設定航線與目標價，機票降價就通知你。Set a route and a target price — we email you when the fare drops.",
    ogDescription:
      "Watch popular routes from Taipei and get an email the moment the fare hits your budget.",
  });

  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader />

      <main className="flex-1">
        {/* Hero */}
        <section className="relative overflow-hidden bg-aura">
          <div className="pointer-events-none absolute inset-0 bg-grid" aria-hidden />
          <div className="relative mx-auto max-w-6xl px-5 pb-24 pt-24 text-center sm:pt-32">
            <div className="animate-fade-up">
              <span className="inline-flex items-center gap-2 rounded-full border border-primary/30 bg-accent/60 px-3.5 py-1.5 text-xs font-medium text-foreground">
                <span className="size-1.5 rounded-full bg-primary animate-pulse-soft" />
                台北出發 · 東京 / 首爾
              </span>
            </div>
            <h1
              className="animate-fade-up mx-auto mt-7 max-w-4xl text-5xl font-semibold leading-[1.05] tracking-tight sm:text-7xl"
              style={{ animationDelay: "80ms" }}
            >
              <span className="text-gradient-primary">Flight Price Notifier</span>
            </h1>
            <p
              className="animate-fade-up mx-auto mt-6 max-w-2xl text-xl font-medium text-foreground sm:text-2xl"
              style={{ animationDelay: "160ms" }}
            >
              設定航線與目標價，機票降價就通知你
            </p>
            <p
              className="animate-fade-up mx-auto mt-3 max-w-xl text-base text-muted-foreground sm:text-lg"
              style={{ animationDelay: "220ms" }}
            >
              Set a route and a target price — we email you when the fare drops.
            </p>
            <div
              className="animate-fade-up mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row"
              style={{ animationDelay: "300ms" }}
            >
              <Button asChild size="lg" className="h-12 px-7 text-base shadow-glow">
                <Link to="/sign-up">
                  免費開始 / Get started <ArrowRight className="size-4" />
                </Link>
              </Button>
              <Button asChild size="lg" variant="outline" className="h-12 px-7 text-base">
                <a href="#features">看看怎麼運作</a>
              </Button>
            </div>
          </div>
        </section>

        {/* Features */}
        <section id="features" className="mx-auto max-w-6xl px-5 py-24">
          <FadeIn className="mx-auto max-w-2xl text-center">
            <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">不用盯價，等通知就好</h2>
            <p className="mt-4 text-muted-foreground">
              適合不在意哪天飛、只想在預算內出發的旅人。你設定，我們盯。
            </p>
          </FadeIn>
          <div className="mt-14 grid gap-5 md:grid-cols-3">
            {features.map((f, i) => (
              <FadeIn key={f.title} delay={i * 100}>
                <FeatureCard {...f} />
              </FadeIn>
            ))}
          </div>
        </section>

        {/* CTA */}
        <section className="mx-auto max-w-6xl px-5 pb-24">
          <FadeIn>
            <div className="relative overflow-hidden rounded-3xl border bg-card px-8 py-14 text-center shadow-card bg-aura">
              <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">準備好用預算內的價格飛了嗎？</h2>
              <p className="mx-auto mt-3 max-w-md text-muted-foreground">
                建立帳號，下一個里程碑就能開始追蹤你的航線。
              </p>
              <Button asChild size="lg" className="mt-8 h-12 px-7 text-base shadow-glow">
                <Link to="/sign-up">
                  建立帳號 / Sign up
                </Link>
              </Button>
            </div>
          </FadeIn>
        </section>
      </main>

      <SiteFooter />
    </div>
  );
}
