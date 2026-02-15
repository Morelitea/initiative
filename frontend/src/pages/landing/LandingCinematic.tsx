import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { Link, useRouter } from "@tanstack/react-router";
import {
  Shield,
  Swords,
  Users,
  Map,
  ListTodo,
  FileText,
  Calendar,
  Sparkles,
  ChevronDown,
  Zap,
  Target,
  Crown,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { LogoIcon } from "@/components/LogoIcon";
import { ModeToggle } from "@/components/ModeToggle";
import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";
import myTasksScreenshot from "@/assets/screenshots/my-tasks.png";
import projectScreenshot from "@/assets/screenshots/project.png";
import documentScreenshot from "@/assets/screenshots/document.png";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FeatureData {
  icon: LucideIcon;
  title: string;
  description: string;
  direction: "left" | "right";
}

interface StatData {
  icon: LucideIcon;
  label: string;
  value: string;
}

interface UseCaseData {
  name: string;
  desc: string;
}

// ---------------------------------------------------------------------------
// Helpers: starfield generation
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

// ---------------------------------------------------------------------------
// Helpers: IntersectionObserver-driven reveal
// ---------------------------------------------------------------------------

function useRevealOnScroll(threshold = 0.15) {
  const ref = useRef<HTMLDivElement>(null);
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsVisible(true);
          observer.unobserve(el);
        }
      },
      { threshold }
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [threshold]);

  return { ref, isVisible };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const Starfield = ({ isDark }: { isDark: boolean }) => (
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

interface FloatingShapeProps {
  className?: string;
  parallaxOffset: number;
  shape: "circle" | "hexagon" | "diamond" | "ring";
  size: number;
  isDark: boolean;
}

const FloatingShape = ({
  className = "",
  parallaxOffset,
  shape,
  size,
  isDark,
}: FloatingShapeProps) => {
  const baseColor = isDark ? "rgba(140, 130, 255, 0.08)" : "rgba(100, 80, 200, 0.06)";
  const borderColor = isDark ? "rgba(140, 130, 255, 0.15)" : "rgba(100, 80, 200, 0.1)";

  const shapeStyles: Record<string, React.CSSProperties> = {
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
      transform: `translateY(${parallaxOffset}px) rotate(45deg)`,
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
// Screenshot frame sub-component
// ---------------------------------------------------------------------------

const ScreenshotFrame = ({
  src,
  alt,
  isDark,
  className = "",
  onClick,
  placeholderText,
}: {
  src?: string;
  alt: string;
  isDark: boolean;
  className?: string;
  onClick?: () => void;
  placeholderText?: string;
}) => (
  <div
    className={`overflow-hidden rounded-xl border shadow-2xl ${src && onClick ? "cursor-pointer" : ""} ${className}`}
    style={{
      borderColor: isDark ? "rgba(140, 130, 255, 0.15)" : "rgba(100, 80, 200, 0.1)",
      background: isDark ? "rgba(20, 16, 40, 0.8)" : "rgba(255, 255, 255, 0.9)",
      transition: "transform 0.3s ease, box-shadow 0.3s ease",
    }}
    onClick={src ? onClick : undefined}
    onMouseEnter={(e) => {
      if (src && onClick) {
        e.currentTarget.style.transform = "scale(1.015)";
        e.currentTarget.style.boxShadow = isDark
          ? "0 25px 60px rgba(140, 130, 255, 0.15)"
          : "0 25px 60px rgba(100, 80, 200, 0.1)";
      }
    }}
    onMouseLeave={(e) => {
      if (src && onClick) {
        e.currentTarget.style.transform = "scale(1)";
        e.currentTarget.style.boxShadow = "";
      }
    }}
  >
    {/* Browser chrome */}
    <div
      className="flex items-center gap-2 px-4 py-3"
      style={{
        borderBottom: `1px solid ${isDark ? "rgba(140, 130, 255, 0.1)" : "rgba(100, 80, 200, 0.06)"}`,
        background: isDark ? "rgba(30, 25, 60, 0.6)" : "rgba(245, 243, 255, 0.8)",
      }}
    >
      <div className="flex gap-1.5">
        <div className="h-3 w-3 rounded-full" style={{ background: "#ff5f57" }} />
        <div className="h-3 w-3 rounded-full" style={{ background: "#ffbd2e" }} />
        <div className="h-3 w-3 rounded-full" style={{ background: "#28c840" }} />
      </div>
      <div
        className="ml-2 flex-1 rounded-md px-3 py-1 text-xs"
        style={{
          background: isDark ? "rgba(140, 130, 255, 0.06)" : "rgba(100, 80, 200, 0.04)",
          color: isDark ? "rgba(200, 200, 220, 0.4)" : "rgba(80, 60, 120, 0.3)",
        }}
      >
        {/* eslint-disable-next-line i18next/no-literal-string */}
        <span>initiativepm.app</span>
      </div>
    </div>
    {/* Screenshot area */}
    {src ? (
      <img src={src} alt={alt} className="block w-full" />
    ) : (
      <div
        className="flex items-center justify-center"
        style={{
          aspectRatio: "16 / 10",
          background: isDark
            ? "linear-gradient(135deg, rgba(30, 25, 60, 0.5) 0%, rgba(50, 40, 90, 0.3) 100%)"
            : "linear-gradient(135deg, rgba(245, 243, 255, 0.5) 0%, rgba(235, 230, 250, 0.3) 100%)",
        }}
      >
        <span
          className="text-sm tracking-widest uppercase"
          style={{ color: isDark ? "rgba(140, 130, 255, 0.25)" : "rgba(100, 80, 200, 0.15)" }}
        >
          {placeholderText ?? "Screenshot"}
        </span>
      </div>
    )}
  </div>
);

const ScreenshotLightbox = ({
  src,
  alt,
  isDark,
  onClose,
}: {
  src: string;
  alt: string;
  isDark: boolean;
  onClose: () => void;
}) => {
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center p-4 sm:p-8"
      style={{ background: isDark ? "rgba(5, 3, 15, 0.92)" : "rgba(0, 0, 0, 0.8)" }}
      onClick={onClose}
    >
      <div
        className="relative max-h-[90vh] max-w-[90vw] overflow-hidden rounded-xl border shadow-2xl"
        style={{
          borderColor: isDark ? "rgba(140, 130, 255, 0.2)" : "rgba(100, 80, 200, 0.15)",
          background: isDark ? "rgba(20, 16, 40, 0.95)" : "rgba(255, 255, 255, 0.98)",
          animation: "lightbox-in 0.3s ease",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Browser chrome */}
        <div
          className="flex items-center gap-2 px-4 py-3"
          style={{
            borderBottom: `1px solid ${isDark ? "rgba(140, 130, 255, 0.1)" : "rgba(100, 80, 200, 0.06)"}`,
            background: isDark ? "rgba(30, 25, 60, 0.6)" : "rgba(245, 243, 255, 0.8)",
          }}
        >
          <div className="flex gap-1.5">
            <button
              className="h-3 w-3 rounded-full transition-opacity hover:opacity-80"
              style={{ background: "#ff5f57" }}
              onClick={onClose}
              aria-label="Close"
            />
            <div className="h-3 w-3 rounded-full" style={{ background: "#ffbd2e" }} />
            <div className="h-3 w-3 rounded-full" style={{ background: "#28c840" }} />
          </div>
          <div
            className="ml-2 flex-1 rounded-md px-3 py-1 text-xs"
            style={{
              background: isDark ? "rgba(140, 130, 255, 0.06)" : "rgba(100, 80, 200, 0.04)",
              color: isDark ? "rgba(200, 200, 220, 0.4)" : "rgba(80, 60, 120, 0.3)",
            }}
          >
            {/* eslint-disable-next-line i18next/no-literal-string */}
            <span>initiativepm.app</span>
          </div>
        </div>
        <img
          src={src}
          alt={alt}
          className="block max-h-[calc(90vh-3rem)]"
          style={{ width: "auto", maxWidth: "90vw" }}
        />
      </div>
      <style>{`
        @keyframes lightbox-in {
          from { opacity: 0; transform: scale(0.92); }
          to { opacity: 1; transform: scale(1); }
        }
      `}</style>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export const LandingCinematic = () => {
  const { t } = useTranslation("landing");
  const { token, loading } = useAuth();
  const { resolvedTheme } = useTheme();
  const router = useRouter();
  const [publicRegistrationEnabled, setPublicRegistrationEnabled] = useState<boolean | null>(null);
  const [scrollY, setScrollY] = useState(0);
  const [navSolid, setNavSolid] = useState(false);
  const [lightboxSrc, setLightboxSrc] = useState<{ src: string; alt: string } | null>(null);

  const isDark = resolvedTheme === "dark";

  // Translated data arrays
  const features: FeatureData[] = useMemo(
    () => [
      {
        icon: Swords,
        title: t("features.campaignTitle"),
        description: t("features.campaignDescription"),
        direction: "left" as const,
      },
      {
        icon: Users,
        title: t("features.partyTitle"),
        description: t("features.partyDescription"),
        direction: "right" as const,
      },
      {
        icon: Map,
        title: t("features.worldTitle"),
        description: t("features.worldDescription"),
        direction: "left" as const,
      },
      {
        icon: ListTodo,
        title: t("features.questTitle"),
        description: t("features.questDescription"),
        direction: "right" as const,
      },
      {
        icon: FileText,
        title: t("features.sessionTitle"),
        description: t("features.sessionDescription"),
        direction: "left" as const,
      },
      {
        icon: Calendar,
        title: t("features.eventTitle"),
        description: t("features.eventDescription"),
        direction: "right" as const,
      },
    ],
    [t]
  );

  const stats: StatData[] = useMemo(
    () => [
      { icon: Target, label: t("stats.initiatives"), value: t("stats.initiativesValue") },
      { icon: Users, label: t("stats.partyMembers"), value: t("stats.partyMembersValue") },
      { icon: Zap, label: t("stats.openSource"), value: t("stats.openSourceValue") },
      { icon: Crown, label: t("stats.selfHosted"), value: t("stats.selfHostedValue") },
    ],
    [t]
  );

  const useCases: UseCaseData[] = useMemo(
    () => [
      { name: t("useCases.ttrpgName"), desc: t("useCases.ttrpgDesc") },
      { name: t("useCases.mmoName"), desc: t("useCases.mmoDesc") },
      { name: t("useCases.esportsName"), desc: t("useCases.esportsDesc") },
      { name: t("useCases.communityName"), desc: t("useCases.communityDesc") },
    ],
    [t]
  );

  // Auth redirect
  useEffect(() => {
    if (!loading && token) {
      router.navigate({ to: "/tasks", replace: true });
    }
  }, [token, loading, router]);

  // Bootstrap status
  useEffect(() => {
    const fetchBootstrapStatus = async () => {
      try {
        const response = await apiClient.get<{
          has_users: boolean;
          public_registration_enabled: boolean;
        }>("/auth/bootstrap");
        setPublicRegistrationEnabled(response.data.public_registration_enabled);
      } catch {
        setPublicRegistrationEnabled(true);
      }
    };
    void fetchBootstrapStatus();
  }, []);

  // Scroll tracking for parallax and nav
  const handleScroll = useCallback(() => {
    const y = window.scrollY;
    setScrollY(y);
    setNavSolid(y > 60);
  }, []);

  useEffect(() => {
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, [handleScroll]);

  // Reveal hooks for each section
  const heroReveal = useRevealOnScroll(0.1);
  const heroScreenshotReveal = useRevealOnScroll(0.15);
  const statsReveal = useRevealOnScroll(0.2);
  const featuresReveal = useRevealOnScroll(0.1);
  const galleryReveal = useRevealOnScroll(0.15);
  const useCasesReveal = useRevealOnScroll(0.15);
  const ctaReveal = useRevealOnScroll(0.2);

  // Loading state
  if (loading) {
    return (
      <div className="bg-background flex min-h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <LogoIcon className="h-12 w-12 animate-pulse" />
          <p className="text-muted-foreground text-sm tracking-widest uppercase">
            {t("hero.loading")}
          </p>
        </div>
      </div>
    );
  }

  if (token) {
    return null;
  }

  // Parallax multipliers for different depth layers
  const layerSlow = scrollY * 0.05;
  const layerMedium = scrollY * 0.12;
  const layerFast = scrollY * 0.2;

  return (
    <div className="bg-background relative min-h-screen overflow-x-hidden">
      {/* Global CSS keyframes */}
      <style>{`
        @keyframes starTwinkle {
          0%, 100% { opacity: 0.2; transform: scale(1); }
          50% { opacity: 1; transform: scale(1.5); }
        }
        @keyframes heroGlow {
          0%, 100% { opacity: 0.4; filter: blur(60px); }
          50% { opacity: 0.7; filter: blur(80px); }
        }
        @keyframes floatSlow {
          0%, 100% { transform: translateY(0px); }
          50% { transform: translateY(-20px); }
        }
        @keyframes floatMedium {
          0%, 100% { transform: translateY(0px); }
          50% { transform: translateY(-12px); }
        }
        @keyframes pulseRing {
          0% { transform: scale(1); opacity: 0.3; }
          50% { transform: scale(1.1); opacity: 0.6; }
          100% { transform: scale(1); opacity: 0.3; }
        }
        @keyframes gradientShift {
          0%, 100% { background-position: 0% 50%; }
          50% { background-position: 100% 50%; }
        }
        @keyframes slideRevealLeft {
          from { opacity: 0; transform: translateX(-60px); }
          to { opacity: 1; transform: translateX(0); }
        }
        @keyframes slideRevealRight {
          from { opacity: 0; transform: translateX(60px); }
          to { opacity: 1; transform: translateX(0); }
        }
        @keyframes fadeUp {
          from { opacity: 0; transform: translateY(40px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes scaleIn {
          from { opacity: 0; transform: scale(0.85); }
          to { opacity: 1; transform: scale(1); }
        }
        @keyframes letterReveal {
          from { opacity: 0; transform: translateY(100%) rotateX(90deg); }
          to { opacity: 1; transform: translateY(0) rotateX(0); }
        }
        @keyframes heroLine {
          from { width: 0%; }
          to { width: 100%; }
        }
      `}</style>

      {/* ================================================================== */}
      {/* Navigation */}
      {/* ================================================================== */}
      <nav
        className={`fixed top-0 right-0 left-0 z-50 transition-all duration-500 ${
          navSolid ? "bg-background/80 shadow-lg backdrop-blur-xl" : "bg-transparent"
        }`}
      >
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div className="text-primary flex items-center gap-2.5 text-xl font-bold tracking-tight">
            <LogoIcon className="h-8 w-8" aria-hidden="true" />
            {/* eslint-disable-next-line i18next/no-literal-string */}
            <span>initiative</span>
          </div>
          <div className="flex items-center gap-3">
            <ModeToggle />
            <Button variant="ghost" className="text-foreground/80 hover:text-foreground" asChild>
              <Link to="/login">{t("nav.signIn")}</Link>
            </Button>
            {publicRegistrationEnabled !== false && (
              <Button asChild>
                <Link to="/register">{t("nav.getStarted")}</Link>
              </Button>
            )}
          </div>
        </div>
      </nav>

      {/* ================================================================== */}
      {/* CHAPTER 1 -- Hero */}
      {/* ================================================================== */}
      <section
        ref={heroReveal.ref}
        className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden"
      >
        {/* Background layers */}
        <div className="aurora-bg absolute inset-0" aria-hidden="true" />

        <div
          className="absolute inset-0 opacity-[0.03]"
          style={{
            backgroundImage: `url(${isDark ? "/images/gridWhite.svg" : "/images/gridBlack.svg"})`,
            backgroundSize: "64px 64px",
            backgroundPosition: "center",
            transform: `translateY(${layerSlow}px)`,
          }}
          aria-hidden="true"
        />

        <Starfield isDark={isDark} />

        {/* Dramatic glow orbs */}
        <div
          className="absolute top-1/4 left-1/2 h-[500px] w-[500px] -translate-x-1/2 -translate-y-1/2 rounded-full md:h-[700px] md:w-[700px]"
          style={{
            background: isDark
              ? "radial-gradient(circle, rgba(100, 80, 240, 0.2) 0%, transparent 70%)"
              : "radial-gradient(circle, rgba(100, 80, 240, 0.08) 0%, transparent 70%)",
            animation: "heroGlow 6s ease-in-out infinite",
            transform: `translate(-50%, calc(-50% + ${layerSlow}px))`,
          }}
          aria-hidden="true"
        />

        <div
          className="absolute top-1/3 right-0 h-[300px] w-[300px] rounded-full md:h-[500px] md:w-[500px]"
          style={{
            background: isDark
              ? "radial-gradient(circle, rgba(200, 100, 255, 0.12) 0%, transparent 70%)"
              : "radial-gradient(circle, rgba(200, 100, 255, 0.05) 0%, transparent 70%)",
            animation: "heroGlow 8s ease-in-out 2s infinite",
            transform: `translateY(${layerMedium}px)`,
          }}
          aria-hidden="true"
        />

        {/* Floating geometric shapes */}
        <FloatingShape
          className="top-[15%] left-[8%]"
          parallaxOffset={-layerMedium}
          shape="hexagon"
          size={80}
          isDark={isDark}
        />
        <FloatingShape
          className="top-[25%] right-[12%]"
          parallaxOffset={-layerFast}
          shape="circle"
          size={60}
          isDark={isDark}
        />
        <FloatingShape
          className="bottom-[20%] left-[15%]"
          parallaxOffset={-layerSlow}
          shape="diamond"
          size={50}
          isDark={isDark}
        />
        <FloatingShape
          className="right-[8%] bottom-[30%]"
          parallaxOffset={-layerMedium}
          shape="ring"
          size={100}
          isDark={isDark}
        />
        <FloatingShape
          className="top-[60%] left-[45%]"
          parallaxOffset={-layerFast}
          shape="hexagon"
          size={40}
          isDark={isDark}
        />
        <FloatingShape
          className="top-[10%] right-[30%]"
          parallaxOffset={-layerSlow}
          shape="ring"
          size={70}
          isDark={isDark}
        />

        {/* Hero content */}
        <div
          className="relative z-10 mx-auto max-w-6xl px-6 text-center"
          style={{ transform: `translateY(${layerSlow * 0.5}px)` }}
        >
          {/* Tagline pill */}
          <div
            className={`mb-8 inline-flex items-center gap-2 rounded-full border px-5 py-2 text-sm font-medium transition-all duration-1000 ${
              heroReveal.isVisible ? "translate-y-0 opacity-100" : "translate-y-8 opacity-0"
            }`}
            style={{
              borderColor: isDark ? "rgba(140, 130, 255, 0.3)" : "rgba(100, 80, 200, 0.15)",
              background: isDark ? "rgba(140, 130, 255, 0.08)" : "rgba(100, 80, 200, 0.05)",
            }}
          >
            <Sparkles className="text-primary h-4 w-4 animate-pulse" />
            <span className="text-primary">{t("hero.tagline")}</span>
          </div>

          {/* Main title -- massive cinematic typography */}
          <h1 className="mb-4 select-none" aria-label={t("hero.titleAria")}>
            <span
              className={`text-muted-foreground/40 block text-lg font-medium tracking-[0.3em] uppercase transition-all delay-200 duration-1000 md:text-xl ${
                heroReveal.isVisible ? "translate-y-0 opacity-100" : "translate-y-8 opacity-0"
              }`}
            >
              {t("hero.preTitle")}
            </span>
            <span
              className={`text-foreground mt-2 block text-6xl font-black tracking-tight transition-all delay-500 duration-1000 sm:text-7xl md:text-8xl lg:text-9xl ${
                heroReveal.isVisible ? "translate-y-0 opacity-100" : "translate-y-12 opacity-0"
              }`}
            >
              {t("hero.titleLine1")}
            </span>
            <span className="relative inline-block">
              <span
                className={`text-primary block text-6xl font-black tracking-tight transition-all delay-700 duration-1000 sm:text-7xl md:text-8xl lg:text-9xl ${
                  heroReveal.isVisible ? "translate-y-0 opacity-100" : "translate-y-12 opacity-0"
                }`}
              >
                {t("hero.titleLine2")}
              </span>
              {/* Underline reveal */}
              <span
                className="bg-primary/30 absolute bottom-0 left-0 h-1 rounded-full md:h-1.5"
                style={{
                  animation: heroReveal.isVisible ? "heroLine 1.2s ease-out 1.2s forwards" : "none",
                  width: 0,
                }}
                aria-hidden="true"
              />
            </span>
          </h1>

          {/* Subtitle */}
          <p
            className={`text-muted-foreground mx-auto mt-6 max-w-2xl text-lg transition-all delay-1000 duration-1000 md:text-xl lg:text-2xl ${
              heroReveal.isVisible ? "translate-y-0 opacity-100" : "translate-y-8 opacity-0"
            }`}
          >
            {t("hero.subtitle")}
          </p>

          {/* CTA buttons */}
          <div
            className={`mt-10 flex flex-col items-center justify-center gap-4 transition-all delay-[1200ms] duration-1000 sm:flex-row ${
              heroReveal.isVisible ? "translate-y-0 opacity-100" : "translate-y-8 opacity-0"
            }`}
          >
            {publicRegistrationEnabled !== false && (
              <Button
                size="lg"
                className="group hover:shadow-primary/25 relative h-12 overflow-hidden px-8 text-base font-semibold transition-all duration-300 hover:scale-105 hover:shadow-lg"
                asChild
              >
                <Link to="/register">
                  <Shield className="mr-2 h-5 w-5 transition-transform duration-300 group-hover:rotate-12" />
                  {t("hero.ctaStart")}
                </Link>
              </Button>
            )}
            <Button
              size="lg"
              variant={publicRegistrationEnabled === false ? "default" : "outline"}
              className="h-12 px-8 text-base font-semibold transition-all duration-300 hover:scale-105"
              asChild
            >
              <Link to="/login">{t("hero.ctaSignIn")}</Link>
            </Button>
          </div>
        </div>

        {/* Scroll indicator */}
        <div
          className={`absolute bottom-8 left-1/2 -translate-x-1/2 transition-all delay-[1800ms] duration-1000 ${
            heroReveal.isVisible ? "translate-y-0 opacity-100" : "translate-y-4 opacity-0"
          }`}
        >
          <div className="flex flex-col items-center gap-2">
            <span className="text-muted-foreground/50 text-xs tracking-[0.2em] uppercase">
              {t("hero.scroll")}
            </span>
            <ChevronDown className="text-muted-foreground/50 h-5 w-5 animate-bounce" />
          </div>
        </div>
      </section>

      {/* ================================================================== */}
      {/* Hero Screenshot */}
      {/* ================================================================== */}
      <section
        ref={heroScreenshotReveal.ref}
        className="relative -mt-16 px-6 pb-12 md:-mt-24 md:pb-20"
      >
        <div
          className={`relative z-20 mx-auto max-w-5xl transition-all duration-1000 ${
            heroScreenshotReveal.isVisible
              ? "translate-y-0 scale-100 opacity-100"
              : "translate-y-12 scale-95 opacity-0"
          }`}
        >
          <ScreenshotFrame
            src={myTasksScreenshot}
            alt={t("heroScreenshot.dashboard")}
            isDark={isDark}
            placeholderText={t("screenshot.placeholder")}
            onClick={() =>
              setLightboxSrc({
                src: myTasksScreenshot,
                alt: t("heroScreenshot.dashboard"),
              })
            }
          />
        </div>
      </section>

      {/* ================================================================== */}
      {/* CHAPTER 2 -- Stats / Social Proof */}
      {/* ================================================================== */}
      <section
        ref={statsReveal.ref}
        className="relative flex min-h-[50vh] items-center justify-center overflow-hidden py-24"
      >
        {/* Divider gradient */}
        <div
          className="absolute inset-0"
          style={{
            background: isDark
              ? "linear-gradient(180deg, transparent 0%, rgba(100, 80, 240, 0.03) 50%, transparent 100%)"
              : "linear-gradient(180deg, transparent 0%, rgba(100, 80, 200, 0.02) 50%, transparent 100%)",
          }}
          aria-hidden="true"
        />

        <div className="relative z-10 mx-auto max-w-5xl px-6">
          <div className="grid grid-cols-2 gap-8 md:grid-cols-4 md:gap-12">
            {stats.map((stat, i) => (
              <div
                key={stat.label}
                className={`flex flex-col items-center gap-3 text-center transition-all duration-700 ${
                  statsReveal.isVisible ? "translate-y-0 opacity-100" : "translate-y-10 opacity-0"
                }`}
                style={{ transitionDelay: `${i * 150}ms` }}
              >
                <div
                  className="flex h-14 w-14 items-center justify-center rounded-2xl md:h-16 md:w-16"
                  style={{
                    background: isDark ? "rgba(140, 130, 255, 0.1)" : "rgba(100, 80, 200, 0.06)",
                    border: `1px solid ${isDark ? "rgba(140, 130, 255, 0.2)" : "rgba(100, 80, 200, 0.1)"}`,
                  }}
                >
                  <stat.icon className="text-primary h-6 w-6 md:h-7 md:w-7" />
                </div>
                <span className="text-foreground text-xl font-bold md:text-2xl">{stat.value}</span>
                <span className="text-muted-foreground text-sm">{stat.label}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ================================================================== */}
      {/* CHAPTER 3 -- Features (alternating slide-in cards) */}
      {/* ================================================================== */}
      <section ref={featuresReveal.ref} className="relative overflow-hidden py-24 md:py-32">
        {/* Background grid */}
        <div
          className="absolute inset-0 opacity-[0.02]"
          style={{
            backgroundImage: `url(${isDark ? "/images/gridWhite.svg" : "/images/gridBlack.svg"})`,
            backgroundSize: "48px 48px",
          }}
          aria-hidden="true"
        />

        <Starfield isDark={isDark} />

        <div className="relative z-10 mx-auto max-w-6xl px-6">
          {/* Section header */}
          <div
            className={`mb-20 text-center transition-all duration-1000 ${
              featuresReveal.isVisible ? "translate-y-0 opacity-100" : "translate-y-10 opacity-0"
            }`}
          >
            <span className="text-primary mb-4 block text-sm font-semibold tracking-[0.2em] uppercase">
              {t("features.sectionLabel")}
            </span>
            <h2 className="text-foreground mb-6 text-4xl font-bold tracking-tight md:text-5xl">
              {t("features.title")}
            </h2>
            <p className="text-muted-foreground mx-auto max-w-2xl text-lg">
              {t("features.description")}
            </p>
          </div>

          {/* Feature cards */}
          <div className="space-y-12 md:space-y-16">
            {features.map((feature, index) => (
              <FeatureCard
                key={feature.title}
                feature={feature}
                index={index}
                parentVisible={featuresReveal.isVisible}
                isDark={isDark}
              />
            ))}
          </div>
        </div>
      </section>

      {/* ================================================================== */}
      {/* Screenshot Gallery */}
      {/* ================================================================== */}
      <section ref={galleryReveal.ref} className="relative overflow-hidden py-24 md:py-32">
        <div
          className="absolute inset-0"
          style={{
            background: isDark
              ? "linear-gradient(180deg, transparent 0%, rgba(100, 80, 240, 0.03) 50%, transparent 100%)"
              : "linear-gradient(180deg, transparent 0%, rgba(100, 80, 200, 0.02) 50%, transparent 100%)",
          }}
          aria-hidden="true"
        />
        <div className="relative z-10 mx-auto max-w-6xl px-6">
          <div
            className={`mb-12 text-center transition-all duration-1000 ${
              galleryReveal.isVisible ? "translate-y-0 opacity-100" : "translate-y-10 opacity-0"
            }`}
          >
            <span className="text-primary mb-4 block text-sm font-semibold tracking-[0.2em] uppercase">
              {t("gallery.sectionLabel")}
            </span>
            <h2 className="text-foreground text-3xl font-bold tracking-tight md:text-4xl">
              {t("gallery.title")}
            </h2>
          </div>
          <div className="grid gap-6 md:grid-cols-2">
            <div
              className={`transition-all duration-700 ${
                galleryReveal.isVisible ? "translate-y-0 opacity-100" : "translate-y-10 opacity-0"
              }`}
              style={{ transitionDelay: "200ms" }}
            >
              <ScreenshotFrame
                src={projectScreenshot}
                alt={t("gallery.projectAlt")}
                isDark={isDark}
                placeholderText={t("screenshot.placeholder")}
                onClick={() =>
                  setLightboxSrc({
                    src: projectScreenshot,
                    alt: t("gallery.projectAlt"),
                  })
                }
              />
              <p className="text-muted-foreground mt-3 text-center text-sm">
                {t("gallery.projectCaption")}
              </p>
            </div>
            <div
              className={`transition-all duration-700 ${
                galleryReveal.isVisible ? "translate-y-0 opacity-100" : "translate-y-10 opacity-0"
              }`}
              style={{ transitionDelay: "400ms" }}
            >
              <ScreenshotFrame
                src={documentScreenshot}
                alt={t("gallery.documentAlt")}
                isDark={isDark}
                placeholderText={t("screenshot.placeholder")}
                onClick={() =>
                  setLightboxSrc({
                    src: documentScreenshot,
                    alt: t("gallery.documentAlt"),
                  })
                }
              />
              <p className="text-muted-foreground mt-3 text-center text-sm">
                {t("gallery.documentCaption")}
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ================================================================== */}
      {/* CHAPTER 4 -- Use Cases */}
      {/* ================================================================== */}
      <section ref={useCasesReveal.ref} className="relative overflow-hidden py-24 md:py-32">
        <div
          className="absolute inset-0"
          style={{
            background: isDark
              ? "linear-gradient(180deg, transparent 0%, rgba(100, 80, 240, 0.04) 50%, transparent 100%)"
              : "linear-gradient(180deg, transparent 0%, rgba(100, 80, 200, 0.02) 50%, transparent 100%)",
          }}
          aria-hidden="true"
        />

        <div className="relative z-10 mx-auto max-w-4xl px-6">
          <div
            className={`rounded-3xl border p-8 backdrop-blur-sm transition-all duration-1000 md:p-14 ${
              useCasesReveal.isVisible ? "translate-y-0 opacity-100" : "translate-y-12 opacity-0"
            }`}
            style={{
              background: isDark ? "rgba(30, 25, 60, 0.5)" : "rgba(255, 255, 255, 0.6)",
              borderColor: isDark ? "rgba(140, 130, 255, 0.12)" : "rgba(100, 80, 200, 0.08)",
            }}
          >
            <div className="text-center">
              <span className="text-primary mb-4 block text-sm font-semibold tracking-[0.2em] uppercase">
                {t("useCases.sectionLabel")}
              </span>
              <h2 className="text-foreground mb-4 text-3xl font-bold tracking-tight md:text-4xl">
                {t("useCases.title")}
              </h2>
              <p className="text-muted-foreground mx-auto mb-10 max-w-2xl">
                {t("useCases.description")}
              </p>
            </div>

            <div className="space-y-4">
              {useCases.map((useCase, i) => (
                <div
                  key={useCase.name}
                  className={`group rounded-xl border p-5 transition-all duration-700 hover:scale-[1.01] ${
                    useCasesReveal.isVisible
                      ? "translate-y-0 opacity-100"
                      : "translate-y-6 opacity-0"
                  }`}
                  style={{
                    transitionDelay: `${300 + i * 150}ms`,
                    background: isDark ? "rgba(140, 130, 255, 0.03)" : "rgba(100, 80, 200, 0.02)",
                    borderColor: isDark ? "rgba(140, 130, 255, 0.08)" : "rgba(100, 80, 200, 0.06)",
                  }}
                >
                  <span className="text-foreground font-semibold">{useCase.name}:</span>{" "}
                  <span className="text-muted-foreground">{useCase.desc}</span>
                </div>
              ))}
            </div>

            {publicRegistrationEnabled !== false && (
              <div
                className={`mt-10 text-center transition-all delay-[900ms] duration-700 ${
                  useCasesReveal.isVisible ? "translate-y-0 opacity-100" : "translate-y-6 opacity-0"
                }`}
              >
                <Button
                  size="lg"
                  className="hover:shadow-primary/20 h-12 px-8 text-base font-semibold transition-all duration-300 hover:scale-105 hover:shadow-lg"
                  asChild
                >
                  <Link to="/register">{t("useCases.cta")}</Link>
                </Button>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ================================================================== */}
      {/* CHAPTER 5 -- Final CTA */}
      {/* ================================================================== */}
      {publicRegistrationEnabled !== false && (
        <section ref={ctaReveal.ref} className="relative overflow-hidden py-32 md:py-40">
          {/* Epic background glow */}
          <div
            className="absolute inset-0"
            style={{
              background: isDark
                ? "radial-gradient(ellipse 80% 50% at 50% 50%, rgba(100, 80, 240, 0.08) 0%, transparent 70%)"
                : "radial-gradient(ellipse 80% 50% at 50% 50%, rgba(100, 80, 200, 0.04) 0%, transparent 70%)",
            }}
            aria-hidden="true"
          />

          <FloatingShape
            className="top-[20%] left-[10%]"
            parallaxOffset={0}
            shape="hexagon"
            size={60}
            isDark={isDark}
          />
          <FloatingShape
            className="right-[10%] bottom-[20%]"
            parallaxOffset={0}
            shape="ring"
            size={80}
            isDark={isDark}
          />

          <div className="relative z-10 mx-auto max-w-3xl px-6 text-center">
            <div
              className={`transition-all duration-1000 ${
                ctaReveal.isVisible
                  ? "translate-y-0 scale-100 opacity-100"
                  : "translate-y-10 scale-95 opacity-0"
              }`}
            >
              <h2 className="text-foreground mb-6 text-4xl font-bold tracking-tight md:text-5xl lg:text-6xl">
                {t("cta.titleReady")}{" "}
                <span className="text-primary">{t("cta.titleHighlight")}</span>?
              </h2>
              <p className="text-muted-foreground mx-auto mb-10 max-w-xl text-lg md:text-xl">
                {t("cta.description")}
              </p>

              <div className="flex flex-col items-center justify-center gap-4 sm:flex-row">
                <Button
                  size="lg"
                  className="group hover:shadow-primary/25 h-14 px-10 text-lg font-semibold transition-all duration-300 hover:scale-105 hover:shadow-xl"
                  asChild
                >
                  <Link to="/register">
                    {t("cta.button")}
                    <Sparkles className="ml-2 h-5 w-5 transition-transform duration-300 group-hover:rotate-12" />
                  </Link>
                </Button>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* ================================================================== */}
      {/* Footer */}
      {/* ================================================================== */}
      <footer
        className="relative border-t"
        style={{
          borderColor: isDark ? "rgba(140, 130, 255, 0.1)" : "rgba(100, 80, 200, 0.06)",
        }}
      >
        <div className="mx-auto max-w-7xl px-6 py-10">
          <div className="flex flex-col items-center justify-between gap-4 md:flex-row">
            <div className="text-primary flex items-center gap-2 font-semibold">
              <LogoIcon className="h-6 w-6" aria-hidden="true" />
              {/* eslint-disable-next-line i18next/no-literal-string */}
              <span>initiative</span>
            </div>
            <p className="text-muted-foreground text-sm">
              {t("footer.copyright", { year: new Date().getFullYear() })}
            </p>
          </div>
        </div>
      </footer>

      {/* Lightbox overlay */}
      {lightboxSrc && (
        <ScreenshotLightbox
          src={lightboxSrc.src}
          alt={lightboxSrc.alt}
          isDark={isDark}
          onClose={() => setLightboxSrc(null)}
        />
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Feature card sub-component (uses its own intersection observer)
// ---------------------------------------------------------------------------

interface FeatureCardProps {
  feature: FeatureData;
  index: number;
  parentVisible: boolean;
  isDark: boolean;
}

const FeatureCard = ({ feature, index, parentVisible, isDark }: FeatureCardProps) => {
  const cardReveal = useRevealOnScroll(0.2);
  const isLeft = feature.direction === "left";

  return (
    <div
      ref={cardReveal.ref}
      className={`flex items-center gap-8 ${
        isLeft ? "md:flex-row" : "md:flex-row-reverse"
      } flex-col`}
    >
      {/* Icon block */}
      <div
        className={`flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl transition-all duration-700 md:h-24 md:w-24 ${
          cardReveal.isVisible && parentVisible
            ? "translate-y-0 scale-100 opacity-100"
            : "translate-y-8 scale-75 opacity-0"
        }`}
        style={{
          transitionDelay: `${index * 100}ms`,
          background: isDark ? "rgba(140, 130, 255, 0.08)" : "rgba(100, 80, 200, 0.05)",
          border: `1px solid ${isDark ? "rgba(140, 130, 255, 0.15)" : "rgba(100, 80, 200, 0.08)"}`,
        }}
      >
        <feature.icon className="text-primary h-9 w-9 md:h-10 md:w-10" />
      </div>

      {/* Text block */}
      <div
        className={`flex-1 transition-all duration-700 ${
          cardReveal.isVisible && parentVisible
            ? "translate-x-0 opacity-100"
            : isLeft
              ? "-translate-x-12 opacity-0"
              : "translate-x-12 opacity-0"
        }`}
        style={{
          transitionDelay: `${index * 100 + 150}ms`,
        }}
      >
        <div
          className="rounded-2xl border p-6 transition-all duration-300 hover:shadow-lg md:p-8"
          style={{
            background: isDark ? "rgba(30, 25, 60, 0.4)" : "rgba(255, 255, 255, 0.6)",
            borderColor: isDark ? "rgba(140, 130, 255, 0.1)" : "rgba(100, 80, 200, 0.06)",
          }}
        >
          <h3 className="text-foreground mb-2 text-xl font-bold">{feature.title}</h3>
          <p className="text-muted-foreground leading-relaxed">{feature.description}</p>
        </div>
      </div>
    </div>
  );
};
