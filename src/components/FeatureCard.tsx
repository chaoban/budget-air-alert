import type { LucideIcon } from "lucide-react";

interface FeatureCardProps {
  icon: LucideIcon;
  title: string;
  subtitle: string;
  body: string;
}

export function FeatureCard({ icon: Icon, title, subtitle, body }: FeatureCardProps) {
  return (
    <div className="group relative h-full rounded-2xl border bg-card p-7 shadow-card transition-colors duration-300 hover:border-primary/40">
      <div className="mb-5 flex size-11 items-center justify-center rounded-full bg-accent text-primary transition-shadow duration-300 group-hover:shadow-glow">
        <Icon className="size-5" />
      </div>
      <h3 className="text-xl font-bold">{title}</h3>
      <p className="mt-1 text-sm italic text-sepia">{subtitle}</p>
      <p className="mt-4 text-sm leading-relaxed text-muted-foreground">{body}</p>
    </div>
  );
}
