import confetti from "canvas-confetti";

import { getLastPointer } from "@/lib/taskCompletionVisualFeedback";

import { PIXEL_COIN_PATH } from "./svg/PixelCoin";
import { PIXEL_DIAMOND_PATH } from "./svg/PixelDiamond";
import { PIXEL_PLUS_PATH } from "./svg/PixelPlus";
import { PIXEL_SQUARE_PATH } from "./svg/PixelSquare";
import { PIXEL_STAR_PATH } from "./svg/PixelStar";
import { PIXEL_TRIANGLE_PATH } from "./svg/PixelTriangle";

// Register the pixel-art shapes once. canvas-confetti's shapeFromPath samples
// the path onto a small offscreen canvas at module init, so doing it lazily
// per-call is wasted work.
const pixelStar = confetti.shapeFromPath({ path: PIXEL_STAR_PATH });
const pixelDiamond = confetti.shapeFromPath({ path: PIXEL_DIAMOND_PATH });
const pixelPlus = confetti.shapeFromPath({ path: PIXEL_PLUS_PATH });
const pixelSquare = confetti.shapeFromPath({ path: PIXEL_SQUARE_PATH });
const pixelTriangle = confetti.shapeFromPath({ path: PIXEL_TRIANGLE_PATH });
const pixelCoin = confetti.shapeFromPath({ path: PIXEL_COIN_PATH });

const PIXEL_PARTY_SHAPES = [pixelStar, pixelDiamond, pixelPlus, pixelSquare, pixelTriangle];
const PIXEL_PARTY_COLORS = [
  "#F87171", // red-400
  "#FBBF24", // amber-400
  "#34D399", // emerald-400
  "#60A5FA", // blue-400
  "#A78BFA", // violet-400
  "#F472B6", // pink-400
];

const COIN_SHAPES = [pixelCoin];
const COIN_COLORS = ["#FFD700", "#F5B800", "#E69900", "#FFEB7A"];

export type ConfettiVariant = "default" | "gold_coin";

const pointerOrigin = (): { x: number; y: number } => {
  const { x, y } = getLastPointer();
  if (typeof window === "undefined") return { x: 0.5, y: 0.5 };
  return {
    x: Math.max(0, Math.min(1, x / window.innerWidth)),
    y: Math.max(0, Math.min(1, y / window.innerHeight)),
  };
};

export const runConfetti = (variant: ConfettiVariant): void => {
  const origin = pointerOrigin();

  if (variant === "gold_coin") {
    confetti({
      particleCount: Math.floor(Math.random() * 20) + 5,
      spread: 60,
      startVelocity: 25,
      gravity: 3,
      ticks: 90,
      origin,
      shapes: COIN_SHAPES,
      colors: COIN_COLORS,
      scalar: 1.2,
    });
    return;
  }

  confetti({
    particleCount: Math.floor(Math.random() * 20) + 20,
    spread: 60,
    startVelocity: 25,
    gravity: 1,
    ticks: 90,
    origin,
    shapes: PIXEL_PARTY_SHAPES,
    colors: PIXEL_PARTY_COLORS,
    scalar: 1.2,
  });
};
