import { useEffect, useState } from "react";

import { PixelHeart } from "./svg/PixelHeart";

interface HeartFloaterProps {
  x: number;
  y: number;
  onDone: () => void;
}

// Pixel heart + "+1" label that drifts up ~80px and fades over 800ms,
// then unmounts via onDone. CSS keyframes are scoped via a unique id so
// back-to-back fires don't collide.
export const HeartFloater = ({ x, y, onDone }: HeartFloaterProps) => {
  const [animationName] = useState(
    () => `pixel-heart-float-${Math.random().toString(36).slice(2)}`
  );

  useEffect(() => {
    const styleEl = document.createElement("style");
    styleEl.textContent = `
      @keyframes ${animationName} {
        0%   { transform: translate(-50%, -50%) translateY(0);    opacity: 1; }
        70%  { opacity: 1; }
        100% { transform: translate(-50%, -50%) translateY(-80px); opacity: 0; }
      }
    `;
    document.head.appendChild(styleEl);
    return () => {
      document.head.removeChild(styleEl);
    };
  }, [animationName]);

  return (
    <div
      onAnimationEnd={onDone}
      style={{
        position: "fixed",
        left: x,
        top: y,
        transform: "translate(-50%, -50%)",
        pointerEvents: "none",
        zIndex: 9999,
        // Heart viewBox is 11x9; match that aspect so the +1 overlay (inset:0,
        // flex-centered) lines up with the heart's true visual center.
        width: 44,
        height: 36,
        animation: `${animationName} 800ms ease-out forwards`,
      }}
    >
      <PixelHeart size={44} style={{ width: "100%", height: "100%", display: "block" }} />
      <span
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#FFFFFF",
          fontWeight: 700,
          fontSize: "16px",
          lineHeight: 1,
          fontFamily: "'Press Start 2P', 'VT323', ui-monospace, monospace",
          // Dark stroke around the white text so it stays readable on the
          // red heart and against any background behind the floater.
          textShadow:
            "1px 0 0 rgba(0,0,0,0.5), -1px 0 0 rgba(0,0,0,0.5), 0 1px 0 rgba(0,0,0,0.5), 0 -1px 0 rgba(0,0,0,0.5)",
        }}
      >
        +1
      </span>
    </div>
  );
};
