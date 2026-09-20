import { Link } from "react-router";
import { Plane } from "lucide-react";

export function BrandMark() {
  return (
    <Link to="/" className="flex items-center gap-2.5 font-semibold tracking-tight text-foreground">
      {/* Vermilion seal (印章) holding the plane mark. */}
      <span className="flex size-8 -rotate-3 items-center justify-center rounded-[3px] bg-seal text-seal-foreground ring-1 ring-seal/40 ring-offset-2 ring-offset-background">
        <Plane className="size-4 -rotate-45" />
      </span>
      <span className="hidden font-serif text-[1.05rem] sm:inline">Flight Price Notifier</span>
    </Link>
  );
}
