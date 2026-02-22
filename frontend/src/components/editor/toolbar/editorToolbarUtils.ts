export type BlockType = "paragraph" | "h1" | "h2" | "h3" | "quote" | "code";
export type Alignment = "left" | "right" | "center" | "justify";
export type ListType = "bullet" | "number" | "check" | "none";

export const FONT_SIZE_OPTIONS = ["14px", "16px", "18px", "20px", "24px", "32px"];
export const DEFAULT_FONT_SIZE = "16px";

export const extractFontSize = (style?: string | null) => {
  if (!style) {
    return null;
  }
  const match = style.match(/font-size:\s*([^;]+)/i);
  return match ? match[1].trim() : null;
};

export const replaceFontSizeInStyle = (style: string, size: string) => {
  const declarations = style
    .split(";")
    .map((declaration) => declaration.trim())
    .filter(Boolean)
    .filter((declaration) => !declaration.toLowerCase().startsWith("font-size"));
  declarations.push(`font-size: ${size}`);
  return declarations.join("; ");
};

export const mergeRegisters = (...fns: Array<() => void>) => {
  return () => {
    for (const unregister of fns) {
      if (typeof unregister === "function") {
        unregister();
      }
    }
  };
};

export const extractYouTubeId = (url: string) => {
  try {
    const parsed = new URL(url);
    if (parsed.hostname === "youtu.be") {
      return parsed.pathname.slice(1);
    }
    if (parsed.hostname.includes("youtube.com")) {
      if (parsed.searchParams.get("v")) {
        return parsed.searchParams.get("v");
      }
      const match = parsed.pathname.match(/\/embed\/([\w-]+)/);
      if (match) {
        return match[1];
      }
    }
  } catch {
    return null;
  }
  return null;
};
