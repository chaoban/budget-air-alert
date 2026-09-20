import { useId } from "react";
import { cn } from "@/lib/utils";

/**
 * Decorative sumi-e branch with watercolor persimmon leaves.
 * Pure SVG (no images), purely ornamental: aria-hidden, no pointer events.
 */

type Leaf = { x: number; y: number; r: number; s: number; c: string; o: number };

const LEAF_PATH = "M0 0 C9 -3 17 8 13 22 C11 30 5 37 0 44 C-5 37 -11 30 -13 22 C-17 8 -9 -3 0 0 Z";
const VEIN_PATH = "M0 2 C1 14 1 28 0 40";

const PALETTE = ["#e8793a", "#d9602a", "#f0a06a", "#c4501e", "#ebb58a", "#e48a4c"];

// Leaves hang from the twigs (rotate 0 = hanging straight down); coordinates in the 520×480 viewBox.
const LEAVES: Leaf[] = [
  // twig A (right, longest)
  [445, 70, -20, 1.2], [462, 108, 25, 1.1], [470, 150, -15, 1.3], [481, 190, 22, 1.0],
  [488, 232, -10, 1.25], [496, 272, 16, 1.1], [500, 318, 0, 1.0], [506, 92, -38, 1.0],
  // twig B
  [334, 96, 22, 1.1], [345, 136, -20, 1.25], [356, 176, 16, 1.0], [352, 216, -12, 1.15], [349, 256, 6, 0.95],
  // twig C / D
  [245, 96, -25, 1.0], [256, 130, 16, 1.1], [156, 96, 22, 0.9], [166, 124, -16, 0.85],
  // along the main branch
  [520, 8, -12, 1.2], [392, 42, -40, 1.0], [292, 62, 36, 0.95], [202, 74, -30, 0.9], [104, 80, 26, 0.8],
].map(([x, y, r, s], i) => ({
  x: x!,
  y: y!,
  r: r!,
  s: s!,
  c: PALETTE[i % PALETTE.length]!,
  o: 0.78 + ((i * 37) % 20) / 100,
}));

export function InkBranch({ className }: { className?: string }) {
  const uid = useId().replace(/:/g, "");
  const wash = `wash-${uid}`;
  const brush = `brush-${uid}`;

  return (
    <svg
      viewBox="0 0 520 480"
      className={cn("pointer-events-none select-none", className)}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        {/* Watercolor: ragged, bleeding edges with pigment pooling. */}
        <filter id={wash} x="-30%" y="-30%" width="160%" height="160%">
          <feTurbulence type="fractalNoise" baseFrequency="0.045" numOctaves="3" seed="3" result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale="7" result="d" />
          <feGaussianBlur in="d" stdDeviation="0.7" result="b" />
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="9" result="g" />
          <feColorMatrix in="g" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -0.55 1.15" result="ga" />
          <feComposite in="b" in2="ga" operator="in" />
        </filter>
        {/* Dry brush: slightly broken ink stroke. */}
        <filter id={brush} x="-10%" y="-10%" width="120%" height="120%">
          <feTurbulence type="fractalNoise" baseFrequency="0.03 0.25" numOctaves="2" seed="5" result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale="2.5" />
        </filter>
      </defs>

      {/* Branches (ink): one main limb entering from the top edge, twigs hanging from it. */}
      <g filter={`url(#${brush})`} fill="none" stroke="#3b2a1e" strokeLinecap="round">
        <path d="M545 -12 C470 22 380 48 300 62 C220 76 140 76 60 82 C40 84 22 90 8 98" strokeWidth="6" opacity="0.8" />
        <path d="M545 -12 C470 22 380 48 300 62 C220 76 140 76 60 82" strokeWidth="2.2" opacity="0.9" transform="translate(-1 2)" />
        <path d="M430 30 C448 90 462 150 478 210 C488 250 496 290 502 330" strokeWidth="2.6" opacity="0.8" />
        <path d="M330 58 C338 110 350 160 352 210 C352 232 350 250 350 262" strokeWidth="2" opacity="0.75" />
        <path d="M240 72 C244 96 250 118 256 140" strokeWidth="1.5" opacity="0.7" />
        <path d="M150 78 C154 94 160 108 166 122" strokeWidth="1.2" opacity="0.65" />
        <path d="M470 24 C490 50 500 70 508 90" strokeWidth="1.2" opacity="0.6" />
      </g>

      {/* Leaves (watercolor). */}
      <g filter={`url(#${wash})`}>
        {LEAVES.map((l, i) => (
          <g key={i} transform={`translate(${l.x} ${l.y}) rotate(${l.r}) scale(${l.s})`}>
            <path d={LEAF_PATH} fill={l.c} opacity={l.o} />
            <path d={LEAF_PATH} fill="#a8401a" opacity={0.18} transform="translate(2 3) scale(0.8)" />
          </g>
        ))}
      </g>

      {/* Fine veins and stems in ink, drawn over the wash. */}
      <g fill="none" stroke="#4a2f1f" strokeLinecap="round" opacity="0.55">
        {LEAVES.filter((_, i) => i % 3 === 0).map((l, i) => (
          <path
            key={i}
            d={VEIN_PATH}
            strokeWidth={0.8 / l.s}
            transform={`translate(${l.x} ${l.y}) rotate(${l.r}) scale(${l.s})`}
          />
        ))}
      </g>
    </svg>
  );
}

/** A single drifting leaf, for small accents (section breaks, cards). */
export function InkLeaf({ className, color = "#e8793a" }: { className?: string; color?: string }) {
  const uid = useId().replace(/:/g, "");
  const wash = `leafwash-${uid}`;
  return (
    <svg
      viewBox="-20 -8 40 58"
      className={cn("pointer-events-none select-none", className)}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <filter id={wash} x="-30%" y="-30%" width="160%" height="160%">
          <feTurbulence type="fractalNoise" baseFrequency="0.07" numOctaves="3" seed="4" result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale="4" />
        </filter>
      </defs>
      <g filter={`url(#${wash})`}>
        <path d={LEAF_PATH} fill={color} opacity="0.85" />
      </g>
      <path d={VEIN_PATH} fill="none" stroke="#4a2f1f" strokeWidth="0.8" opacity="0.5" />
    </svg>
  );
}
