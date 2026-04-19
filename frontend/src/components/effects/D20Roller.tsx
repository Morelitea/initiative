import { useEffect, useState } from "react";

import { PixelD20 } from "./svg/PixelD20";
import { PixelSparkle } from "./svg/PixelSparkle";

interface D20RollerProps {
  /** Viewport-pixel coordinates the die centers on (usually the click site). */
  x: number;
  y: number;
  onDone: () => void;
}

const ROLL_INTERVAL_MS = 80;
const ROLL_DURATION_MS = 400;
const SPARKLE_DURATION_MS = 600;
const TOTAL_DURATION_MS = ROLL_DURATION_MS + SPARKLE_DURATION_MS;

// Pixel d20 that rapidly cycles through 1–19 face values for ~600ms then
// settles on a Natural 20 with a sparkle burst. Pure setTimeout / setInterval —
// no extra animation lib.
export const D20Roller = ({ x, y, onDone }: D20RollerProps) => {
  const [face, setFace] = useState<number>(() => 1 + Math.floor(Math.random() * 19));
  const [phase, setPhase] = useState<"rolling" | "settled">("rolling");
  const [animationName] = useState(() => `pixel-d20-settle-${Math.random().toString(36).slice(2)}`);

  // Inject a one-off keyframes block for the settle pop.
  useEffect(() => {
    const styleEl = document.createElement("style");
    styleEl.textContent = `
      @keyframes ${animationName} {
        0%   { transform: translate(-50%, -50%) scale(1.0); }
        25%  { transform: translate(-50%, -50%) scale(1.4); }
        50%  { transform: translate(-50%, -50%) scale(0.95); }
        75%  { transform: translate(-50%, -50%) scale(1.1); }
        100% { transform: translate(-50%, -50%) scale(1.0); opacity: 0; }
      }
    `;
    document.head.appendChild(styleEl);
    return () => {
      document.head.removeChild(styleEl);
    };
  }, [animationName]);

  useEffect(() => {
    const interval = setInterval(() => {
      setFace(1 + Math.floor(Math.random() * 19));
    }, ROLL_INTERVAL_MS);
    const settle = setTimeout(() => {
      clearInterval(interval);
      setFace(20);
      setPhase("settled");
    }, ROLL_DURATION_MS);
    const finish = setTimeout(onDone, TOTAL_DURATION_MS);
    return () => {
      clearInterval(interval);
      clearTimeout(settle);
      clearTimeout(finish);
    };
  }, [onDone]);

  // Five sparkles at 72° intervals around the die. Computed in pixel space so
  // the layout doesn't drift when the die size changes.
  const dieSize = 120;
  const sparkleSize = 16;
  const sparkleRadius = dieSize / 2 + 8; // sit just outside the silhouette
  const sparklePositions = Array.from({ length: 5 }, (_, i) => {
    // Start at the top (-90°) and step clockwise.
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / 5;
    return {
      x: dieSize / 2 + Math.cos(angle) * sparkleRadius,
      y: dieSize / 2 + Math.sin(angle) * sparkleRadius,
    };
  });

  return (
    <div
      style={{
        position: "fixed",
        left: x,
        top: y,
        transform: "translate(-50%, -50%)",
        pointerEvents: "none",
        zIndex: 9999,
        width: dieSize,
        height: dieSize,
        animation:
          phase === "settled"
            ? `${animationName} ${SPARKLE_DURATION_MS}ms ease-out forwards`
            : undefined,
      }}
    >
      <PixelD20 value={face} size={dieSize} />
      {phase === "settled" &&
        sparklePositions.map((pos, i) => (
          <div
            key={i}
            style={{
              position: "absolute",
              left: pos.x,
              top: pos.y,
              transform: "translate(-50%, -50%)",
            }}
          >
            <PixelSparkle size={sparkleSize} />
          </div>
        ))}
    </div>
  );
};
