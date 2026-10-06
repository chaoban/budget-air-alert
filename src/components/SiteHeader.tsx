import { Link } from "react-router";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BrandMark } from "@/components/BrandMark";
import { useAuthSession } from "@/hooks/useAuthSession";

/** Public header: shows Sign in, or a Dashboard link when already signed in. */
export function SiteHeader() {
  const { user, loading } = useAuthSession();

  return (
    <header className="sticky top-0 z-40 border-b border-border/60 bg-background/70 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
        <BrandMark />
        <div className="flex items-center gap-4 sm:gap-6">
          <nav
            aria-label="頁面導覽"
            className="flex items-center gap-4 text-sm text-muted-foreground sm:gap-6"
          >
            <a href="/#pricing" className="transition-colors hover:text-foreground">
              收費方案
            </a>
            <a href="#contact" className="transition-colors hover:text-foreground">
              聯絡我們
            </a>
          </nav>
          {user && !loading ? (
            <Button asChild>
              <Link to="/app">
                儀表板 / Dashboard <ArrowRight className="size-4" />
              </Link>
            </Button>
          ) : (
            <Button asChild>
              <Link to="/sign-in">Sign in / 登入</Link>
            </Button>
          )}
        </div>
      </div>
    </header>
  );
}
