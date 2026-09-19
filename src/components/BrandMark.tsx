import { Link } from "@tanstack/react-router";
import { Plane } from "lucide-react";

export function BrandMark() {
  return (
    <Link to="/" className="flex items-center gap-2.5 font-semibold tracking-tight text-foreground">
      <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-glow">
        <Plane className="size-4 -rotate-45" />
      </span>
      <span className="hidden sm:inline">Flight Price Notifier</span>
    </Link>
  );
}
