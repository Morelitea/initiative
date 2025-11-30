type Theme = "light" | "dark";

const FALLBACK_ACCENT = "#111827";

const normalizeHex = (value: string | undefined | null) => {
  if (!value) {
    return FALLBACK_ACCENT;
  }
  return value.startsWith("#") ? value : `#${value}`;
};

const faviconAccent: Record<Theme, string> = {
  light: FALLBACK_ACCENT,
  dark: FALLBACK_ACCENT,
};

const ensureIconLink = () => {
  if (typeof document === "undefined") {
    return null;
  }
  const existing = document.querySelector<HTMLLinkElement>('link[rel="icon"][data-accent-favicon]');
  if (existing) {
    return existing;
  }
  const fallback = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (fallback) {
    fallback.dataset.accentFavicon = "true";
    return fallback;
  }
  const link = document.createElement("link");
  link.rel = "icon";
  link.type = "image/svg+xml";
  link.dataset.accentFavicon = "true";
  document.head.appendChild(link);
  return link;
};

const buildFaviconSvg = (color: string = "#fff") => `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 438 471">
  <path fill="${color}" d="M218.82 470.128a20.242 20.242 0 0 1-8.27-1.639L14.387 384.823C5.724 381.128 0 371.834 0 361.464v-238.72c0-.652.023-1.3.067-1.943.298-4.21 1.546-8.282 3.62-11.81 1.54-2.615 3.524-4.918 5.884-6.758a21.969 21.969 0 0 1 2.994-1.966l196.161-97.74C211.98.753 215.431-.054 218.82.002c3.39-.057 6.84.751 10.094 2.523l196.161 97.741a21.969 21.969 0 0 1 2.994 1.966c2.36 1.84 4.345 4.143 5.885 6.757 2.073 3.53 3.321 7.601 3.62 11.811.043.643.066 1.291.066 1.942v238.721c0 10.37-5.724 19.664-14.388 23.36l-196.16 83.665a20.242 20.242 0 0 1-8.272 1.64ZM137.623 188.27a24.668 24.668 0 0 1-22.62 1.39l-70.298-31.046v185.628l120.247 51.288V243.097a53.369 53.369 0 0 1 27.81-46.853 53.367 53.367 0 0 1 52.116 0l.5.28a53.369 53.369 0 0 1 27.31 46.573V395.53l120.247-51.288V158.613l-70.648 31.25a24.67 24.67 0 0 1-22.634-1.383l-.186-.112a24.669 24.669 0 0 1 2.616-43.713l56.324-25.09L218.82 52.643 79.233 119.565l55.934 24.884a24.668 24.668 0 0 1 2.626 43.718l-.17.102Z"/><ellipse fill="${color}" cx="257.233" cy="209.745" rx="52.118" ry="36.171" transform="matrix(.76806 0 0 1.13407 21.073 -109.942)"/>
</svg>
`;

const updateFaviconHref = (color: string) => {
  const link = ensureIconLink();
  if (!link) {
    return;
  }
  const svg = buildFaviconSvg(color);
  link.href = `data:image/svg+xml,${encodeURIComponent(svg)}`;
};

const updateThemeMeta = (color: string) => {
  if (typeof document === "undefined") {
    return;
  }
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    meta.setAttribute("content", color);
  }
};

export const setAccentFaviconColors = (light: string, dark: string) => {
  faviconAccent.light = normalizeHex(light);
  faviconAccent.dark = normalizeHex(dark);
};

export const syncFaviconWithTheme = (theme: Theme) => {
  const color = faviconAccent[theme] ?? FALLBACK_ACCENT;
  updateFaviconHref(color);
  updateThemeMeta(color);
};
