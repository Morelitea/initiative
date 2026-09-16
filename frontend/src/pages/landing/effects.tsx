/**
 * The landing page's set dressing: a starfield, floating shapes that drift
 * against the scroll, and the observer that lets a section fade in the first
 * time it is scrolled into view.
 */

import { useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Reveal-on-scroll
// ---------------------------------------------------------------------------

/** Whether any part of the element is inside the viewport right now. */
const inViewport = (el: HTMLElement) => {
  const rect = el.getBoundingClientRect();
  const height = window.innerHeight || document.documentElement.clientHeight;
  return rect.bottom > 0 && rect.top < height && rect.height > 0;
};

/**
 * Reveal an element the first time it is scrolled into view.
 *
 * The observer does the scrolling case. The rest guards the case where the
 * element is already in view when nobody scrolled: a refresh restores the
 * old scroll position after this effect has run, a tab is shown again from
 * the back-forward cache, or the observer's first report is late. Each of
 * those re-checks the plain geometry, and once anything says visible the
 * element stays visible.
 */
export function useRevealOnScroll<T extends HTMLElement = HTMLDivElement>(threshold = 0.15) {
  const ref = useRef<T>(null);
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // jsdom and very old browsers have no observer; showing everything is the
    // honest fallback rather than a page that never fades in.
    if (typeof IntersectionObserver === "undefined" || inViewport(el)) {
      setIsVisible(true);
      return;
    }

    let done = false;
    const show = () => {
      if (done) return;
      done = true;
      setIsVisible(true);
      cleanup();
    };
    const recheck = () => {
      if (inViewport(el)) show();
    };
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) show();
      },
      { threshold }
    );
    const timer = window.setTimeout(recheck, 1500);
    const cleanup = () => {
      observer.disconnect();
      window.clearTimeout(timer);
      window.removeEventListener("pageshow", recheck);
      window.removeEventListener("scroll", recheck);
      window.removeEventListener("resize", recheck);
    };

    observer.observe(el);
    window.addEventListener("pageshow", recheck);
    window.addEventListener("scroll", recheck, { passive: true });
    window.addEventListener("resize", recheck);
    return cleanup;
  }, [threshold]);

  return { ref, isVisible };
}

/** The transition classes a revealed block swaps between. */
export const reveal = (visible: boolean, hidden = "translate-y-8 opacity-0") =>
  visible ? "translate-y-0 opacity-100" : hidden;

// ---------------------------------------------------------------------------
// Starfield
// ---------------------------------------------------------------------------

interface Star {
  id: number;
  x: number;
  y: number;
  size: number;
  opacity: number;
  animationDuration: number;
  animationDelay: number;
}

function generateStars(count: number): Star[] {
  const stars: Star[] = [];
  for (let i = 0; i < count; i++) {
    stars.push({
      id: i,
      x: Math.random() * 100,
      y: Math.random() * 100,
      size: Math.random() * 2 + 0.5,
      opacity: Math.random() * 0.7 + 0.1,
      animationDuration: Math.random() * 4 + 2,
      animationDelay: Math.random() * 5,
    });
  }
  return stars;
}

const STARS = generateStars(80);

export const Starfield = ({ isDark }: { isDark: boolean }) => (
  <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
    {STARS.map((star) => (
      <div
        key={star.id}
        className="absolute rounded-full"
        style={{
          left: `${star.x}%`,
          top: `${star.y}%`,
          width: `${star.size}px`,
          height: `${star.size}px`,
          backgroundColor: isDark
            ? `rgba(200, 210, 255, ${star.opacity})`
            : `rgba(80, 60, 120, ${star.opacity * 0.35})`,
          animation: `starTwinkle ${star.animationDuration}s ease-in-out ${star.animationDelay}s infinite`,
        }}
      />
    ))}
  </div>
);

// ---------------------------------------------------------------------------
// Floating shapes
// ---------------------------------------------------------------------------

interface FloatingShapeProps {
  className?: string;
  parallaxOffset: number;
  shape: "circle" | "hexagon" | "diamond" | "ring";
  size: number;
  isDark: boolean;
}

export const FloatingShape = ({
  className = "",
  parallaxOffset,
  shape,
  size,
  isDark,
}: FloatingShapeProps) => {
  const baseColor = isDark ? "rgba(140, 130, 255, 0.08)" : "rgba(100, 80, 200, 0.06)";
  const borderColor = isDark ? "rgba(140, 130, 255, 0.15)" : "rgba(100, 80, 200, 0.1)";

  const shapeStyles: Record<FloatingShapeProps["shape"], React.CSSProperties> = {
    circle: {
      width: size,
      height: size,
      borderRadius: "50%",
      background: baseColor,
      border: `1px solid ${borderColor}`,
    },
    hexagon: {
      width: size,
      height: size,
      clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)",
      background: baseColor,
    },
    diamond: {
      width: size,
      height: size,
      background: baseColor,
      border: `1px solid ${borderColor}`,
    },
    ring: {
      width: size,
      height: size,
      borderRadius: "50%",
      border: `2px solid ${borderColor}`,
      background: "transparent",
    },
  };

  return (
    <div
      className={`pointer-events-none absolute transition-transform duration-100 ease-out ${className}`}
      style={{
        ...shapeStyles[shape],
        transform:
          shape === "diamond"
            ? `translateY(${parallaxOffset}px) rotate(45deg)`
            : `translateY(${parallaxOffset}px)`,
      }}
      aria-hidden="true"
    />
  );
};

// ---------------------------------------------------------------------------
// Keyframes every section leans on
// ---------------------------------------------------------------------------

export const LANDING_KEYFRAMES = `
  @keyframes starTwinkle {
    0%, 100% { opacity: 0.2; transform: scale(1); }
    50% { opacity: 1; transform: scale(1.5); }
  }
  @keyframes heroGlow {
    0%, 100% { opacity: 0.4; filter: blur(60px); }
    50% { opacity: 0.7; filter: blur(80px); }
  }
  @keyframes heroLine {
    from { width: 0%; }
    to { width: 100%; }
  }
  @keyframes ribbonScroll {
    from { transform: translateX(0); }
    to { transform: translateX(-50%); }
  }
  @keyframes cardFloat {
    0%, 100% { transform: translateY(0) rotate(var(--tilt, 0deg)); }
    50% { transform: translateY(-10px) rotate(var(--tilt, 0deg)); }
  }
  /* The header's in-page links glide rather than jump. Scoped to the landing
     page by living in its own style block, and dropped for anybody who has
     asked the system for less movement. */
  html { scroll-behavior: smooth; }
  @media (prefers-reduced-motion: reduce) {
    html { scroll-behavior: auto; }
    .landing-ribbon__track { animation: none !important; }
    .landing-float { animation: none !important; }
  }
`;
