import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { Loader2, MailCheck } from "lucide-react";
import { toast } from "sonner";
import { supabase } from "@/integrations/supabase/client";
import { AuthShell } from "@/components/AuthShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { usePageMeta } from "@/hooks/usePageMeta";

export function ForgotPasswordPage() {
  usePageMeta({
    title: "忘記密碼 / Forgot password — Flight Price Notifier",
    description: "Send yourself a password reset link.",
  });
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const { error } = await supabase.auth.resetPasswordForEmail(email.trim(), {
        redirectTo: `${window.location.origin}/reset-password`,
      });
      if (error) throw error;
      setSent(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthShell title="忘記密碼" subtitle="We'll email you a link to set a new password.">
      {sent ? (
        <div className="space-y-4 text-sm leading-relaxed">
          <div className="flex size-10 items-center justify-center rounded-xl bg-accent text-primary">
            <MailCheck className="size-5" />
          </div>
          <p>
            如果 <span className="font-medium">{email}</span>{" "}
            有註冊，重設密碼的信已經寄出。請點信裡的連結設定新密碼（記得看一下垃圾郵件匣）。
          </p>
          <p className="text-muted-foreground">
            If that email is registered, a reset link is on its way.
          </p>
          <Button variant="outline" className="w-full" onClick={() => setSent(false)}>
            沒收到？重新寄送
          </Button>
        </div>
      ) : (
        <form onSubmit={onSubmit} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              required
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <Button type="submit" className="h-11 w-full shadow-glow" disabled={submitting}>
            {submitting && <Loader2 className="size-4 animate-spin" />}
            寄送重設連結 / Send reset link
          </Button>
        </form>
      )}
      <p className="mt-5 text-center text-sm text-muted-foreground">
        想起來了？{" "}
        <Link
          to="/sign-in"
          className="font-medium text-foreground underline-offset-4 hover:underline"
        >
          回到登入 / Sign in
        </Link>
      </p>
    </AuthShell>
  );
}
