import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { supabase } from "@/integrations/supabase/client";
import { AuthShell } from "@/components/AuthShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { usePageMeta } from "@/hooks/usePageMeta";

/**
 * Landing page for the Supabase recovery link. The client picks the recovery session
 * out of the URL automatically (detectSessionInUrl); we then let the user set a new password.
 */
export function ResetPasswordPage() {
  usePageMeta({
    title: "設定新密碼 / Reset password — Flight Price Notifier",
    description: "Choose a new password for your account.",
  });
  const navigate = useNavigate();
  const [status, setStatus] = useState<"checking" | "ready" | "invalid">("checking");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let settled = false;
    const { data } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === "PASSWORD_RECOVERY" || session) {
        settled = true;
        setStatus("ready");
      }
    });
    // Give the client a moment to parse the link; no session afterwards = expired/invalid link.
    const timer = window.setTimeout(async () => {
      if (settled) return;
      const { data: s } = await supabase.auth.getSession();
      setStatus(s.session ? "ready" : "invalid");
    }, 1500);
    return () => {
      data.subscription.unsubscribe();
      window.clearTimeout(timer);
    };
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (password.length < 6) {
      toast.error("密碼至少 6 個字元 / At least 6 characters");
      return;
    }
    if (password !== confirm) {
      toast.error("兩次輸入的密碼不一致 / Passwords do not match");
      return;
    }
    setSubmitting(true);
    try {
      const { error } = await supabase.auth.updateUser({ password });
      if (error) throw error;
      toast.success("密碼已更新 / Password updated");
      navigate("/app", { replace: true });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthShell title="設定新密碼" subtitle="Choose a new password for your account.">
      {status === "checking" && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> 驗證連結中…
        </p>
      )}
      {status === "invalid" && (
        <div className="space-y-4 text-sm leading-relaxed">
          <p>這個重設連結已失效或已使用過。請重新申請一次。</p>
          <Button asChild className="w-full">
            <Link to="/forgot-password">重新寄送重設連結</Link>
          </Button>
        </div>
      )}
      {status === "ready" && (
        <form onSubmit={onSubmit} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="password">新密碼 / New password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="new-password"
              required
              minLength={6}
              placeholder="至少 6 個字元"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirm">再輸入一次 / Confirm</Label>
            <Input
              id="confirm"
              type="password"
              autoComplete="new-password"
              required
              minLength={6}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </div>
          <Button type="submit" className="h-11 w-full shadow-glow" disabled={submitting}>
            {submitting && <Loader2 className="size-4 animate-spin" />}
            更新密碼 / Update password
          </Button>
        </form>
      )}
    </AuthShell>
  );
}
