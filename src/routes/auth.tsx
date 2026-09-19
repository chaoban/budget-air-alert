import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";
import { z } from "zod";
import { BrandMark } from "@/components/BrandMark";
import { AuthForm } from "@/components/AuthForm";
import { useAuthSession } from "@/hooks/useAuthSession";

const searchSchema = z.object({
  mode: z.enum(["signin", "signup"]).catch("signin"),
});

export const Route = createFileRoute("/auth")({
  validateSearch: searchSchema,
  head: () => ({
    meta: [
      { title: "登入 / Sign in — Flight Price Notifier" },
      { name: "description", content: "Sign in or create an account to start watching flight fares from Taipei." },
      { property: "og:title", content: "登入 / Sign in — Flight Price Notifier" },
      { property: "og:description", content: "Sign in or create an account to start watching flight fares from Taipei." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: AuthPage,
});

function AuthPage() {
  const { mode } = Route.useSearch();
  const { user, loading } = useAuthSession();
  const navigate = useNavigate();
  const isSignUp = mode === "signup";

  // Already signed in → go straight to the dashboard.
  useEffect(() => {
    if (!loading && user) navigate({ to: "/app", replace: true });
  }, [loading, user, navigate]);

  return (
    <div className="relative flex min-h-screen flex-col bg-aura">
      <div className="pointer-events-none absolute inset-0 bg-grid" aria-hidden />
      <header className="relative mx-auto flex h-16 w-full max-w-6xl items-center px-5">
        <BrandMark />
      </header>
      <main className="relative flex flex-1 items-center justify-center px-5 pb-20">
        <div className="animate-fade-up w-full max-w-md rounded-2xl border bg-card/80 p-8 shadow-card backdrop-blur">
          <h1 className="text-2xl font-semibold tracking-tight">
            {isSignUp ? "建立帳號" : "歡迎回來"}
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            {isSignUp
              ? "Create your account to start tracking fares."
              : "Sign in to your Flight Price Notifier account."}
          </p>
          <div className="mt-7">
            <AuthForm key={mode} mode={mode} />
          </div>
        </div>
      </main>
    </div>
  );
}
