/**
 * Audio + haptic feedback for the counter +/- buttons. Mirror of
 * `taskCompletionFeedback.ts` but lighter: one short tick sound (direction-
 * specific) and a single short haptic tap per press — no preference gating
 * yet. Imported by `useSteppedCount`, which is the single funnel for both
 * the row-card buttons and the focus-view buttons.
 */

import { Capacitor } from "@capacitor/core";

import tickUrl from "@/assets/tick.wav";
import tickReverseUrl from "@/assets/tick_reverse.wav";

// Lazily-constructed Audio elements so back-to-back fires don't churn DOM
// elements. `currentTime = 0` rewinds for re-play in a rapid burst.
let tickUpAudio: HTMLAudioElement | null = null;
let tickDownAudio: HTMLAudioElement | null = null;

const playTickSound = (direction: "up" | "down"): void => {
  if (typeof window === "undefined") return;
  if (direction === "up") {
    if (!tickUpAudio) {
      tickUpAudio = new Audio(tickUrl);
      tickUpAudio.volume = 0.6;
    }
    tickUpAudio.currentTime = 0;
    void tickUpAudio.play().catch(() => {
      // Autoplay policies / no audio device — silent failure is fine.
    });
  } else {
    if (!tickDownAudio) {
      tickDownAudio = new Audio(tickReverseUrl);
      tickDownAudio.volume = 0.6;
    }
    tickDownAudio.currentTime = 0;
    void tickDownAudio.play().catch(() => {});
  }
};

/**
 * Single short haptic tap. Native goes through the Haptics plugin so iOS
 * WKWebView works; web uses the Vibration API (Android only, no-op on
 * iOS Safari).
 */
const triggerCounterHaptic = (): void => {
  if (Capacitor.isNativePlatform()) {
    void import("@capacitor/haptics").then(({ Haptics, ImpactStyle }) => {
      void Haptics.impact({ style: ImpactStyle.Light });
    });
    return;
  }
  if (typeof navigator !== "undefined" && typeof navigator.vibrate === "function") {
    navigator.vibrate(20);
  }
};

export const fireCounterStepFeedback = (direction: "up" | "down"): void => {
  playTickSound(direction);
  triggerCounterHaptic();
};
