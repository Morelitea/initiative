import { useEffect } from "react";
import { useTranslation } from "react-i18next";

const FRAME_HOST = "initiative";

const chromeStyle = (isDark: boolean) => ({
  borderBottom: `1px solid ${isDark ? "rgba(140, 130, 255, 0.1)" : "rgba(100, 80, 200, 0.06)"}`,
  background: isDark ? "rgba(30, 25, 60, 0.6)" : "rgba(245, 243, 255, 0.8)",
});

const addressStyle = (isDark: boolean) => ({
  background: isDark ? "rgba(140, 130, 255, 0.06)" : "rgba(100, 80, 200, 0.04)",
  color: isDark ? "rgba(200, 200, 220, 0.4)" : "rgba(80, 60, 120, 0.3)",
});

/** A screenshot inside a little browser window, optionally opening a lightbox. */
export const ScreenshotFrame = ({
  src,
  alt,
  isDark,
  className = "",
  onClick,
}: {
  src: string;
  alt: string;
  isDark: boolean;
  className?: string;
  onClick?: () => void;
}) => {
  const isInteractive = Boolean(onClick);
  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: role and handlers are applied together when isInteractive is true; biome can't see the conditional
    <div
      className={`overflow-hidden rounded-xl border shadow-2xl transition-[transform,box-shadow] duration-300 ${
        isInteractive ? "cursor-pointer hover:scale-[1.015] hover:shadow-primary/15" : ""
      } ${className}`}
      style={{
        borderColor: isDark ? "rgba(140, 130, 255, 0.15)" : "rgba(100, 80, 200, 0.1)",
        background: isDark ? "rgba(20, 16, 40, 0.8)" : "rgba(255, 255, 255, 0.9)",
      }}
      role={isInteractive ? "button" : undefined}
      tabIndex={isInteractive ? 0 : undefined}
      onClick={onClick}
      onKeyDown={
        isInteractive
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick?.();
              }
            }
          : undefined
      }
    >
      <div className="flex items-center gap-2 px-4 py-3" style={chromeStyle(isDark)}>
        <div className="flex gap-1.5">
          <div className="h-3 w-3 rounded-full" style={{ background: "#ff5f57" }} />
          <div className="h-3 w-3 rounded-full" style={{ background: "#ffbd2e" }} />
          <div className="h-3 w-3 rounded-full" style={{ background: "#28c840" }} />
        </div>
        <div className="ml-2 flex-1 rounded-md px-3 py-1 text-xs" style={addressStyle(isDark)}>
          <span>{FRAME_HOST}</span>
        </div>
      </div>
      <img src={src} alt={alt} className="block w-full" loading="lazy" />
    </div>
  );
};

export const ScreenshotLightbox = ({
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
  const { t } = useTranslation("common");

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
    // biome-ignore lint/a11y/useKeyWithClickEvents: keyboard dismiss is handled by the Escape listener in useEffect above and the close <button> below
    <div
      role="dialog"
      aria-modal="true"
      aria-label={alt}
      className="fixed inset-0 z-[9999] flex items-center justify-center p-4 sm:p-8"
      style={{ background: isDark ? "rgba(5, 3, 15, 0.92)" : "rgba(0, 0, 0, 0.8)" }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="relative max-h-[90vh] max-w-[90vw] overflow-hidden rounded-xl border shadow-2xl"
        style={{
          borderColor: isDark ? "rgba(140, 130, 255, 0.2)" : "rgba(100, 80, 200, 0.15)",
          background: isDark ? "rgba(20, 16, 40, 0.95)" : "rgba(255, 255, 255, 0.98)",
          animation: "lightbox-in 0.3s ease",
        }}
      >
        <div className="flex items-center gap-2 px-4 py-3" style={chromeStyle(isDark)}>
          <div className="flex gap-1.5">
            <button
              type="button"
              className="h-3 w-3 rounded-full transition-opacity hover:opacity-80"
              style={{ background: "#ff5f57" }}
              onClick={onClose}
              aria-label={t("close")}
            />
            <div className="h-3 w-3 rounded-full" style={{ background: "#ffbd2e" }} />
            <div className="h-3 w-3 rounded-full" style={{ background: "#28c840" }} />
          </div>
          <div className="ml-2 flex-1 rounded-md px-3 py-1 text-xs" style={addressStyle(isDark)}>
            <span>{FRAME_HOST}</span>
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
