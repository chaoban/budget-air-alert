import { Mail, Phone } from "lucide-react";
import { SaisaiLogo } from "@/components/SaisaiLogo";
import { CONTACT } from "@/lib/pricing";

export function SiteFooter() {
  return (
    <footer className="border-t border-border/60">
      <div className="mx-auto flex max-w-6xl flex-col items-center gap-8 px-5 pb-6 pt-10 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex flex-col items-center gap-3 sm:items-start">
          <SaisaiLogo className="h-6" />
          <span className="text-sm text-muted-foreground">
            Flight Price Notifier · 機票降價通知 · 台北出發
          </span>
        </div>

        <section
          id="contact"
          aria-labelledby="contact-heading"
          className="scroll-mt-20 text-center sm:text-left"
        >
          <h2 id="contact-heading" className="text-sm font-semibold text-foreground">
            聯絡我們
          </h2>
          <dl className="mt-3 space-y-2 text-sm text-muted-foreground">
            <div className="flex items-center justify-center gap-1 sm:justify-start">
              <Phone className="mr-1 size-4 shrink-0 text-primary" aria-hidden />
              <dt>電話：</dt>
              <dd>
                <a href={CONTACT.phoneHref} className="text-foreground hover:text-primary">
                  {CONTACT.phone}
                </a>
              </dd>
            </div>
            <div className="flex items-center justify-center gap-1 sm:justify-start">
              <Mail className="mr-1 size-4 shrink-0 text-primary" aria-hidden />
              <dt>信箱：</dt>
              <dd>
                <a
                  href={`mailto:${CONTACT.email}`}
                  className="break-all text-foreground hover:text-primary"
                >
                  {CONTACT.email}
                </a>
              </dd>
            </div>
          </dl>
        </section>
      </div>

      <div className="mx-auto max-w-6xl px-5 pb-8">
        <p className="border-t border-border/60 pt-5 text-center text-xs text-muted-foreground sm:text-left">
          © 2026 {CONTACT.company}. All rights reserved.
        </p>
      </div>
    </footer>
  );
}
