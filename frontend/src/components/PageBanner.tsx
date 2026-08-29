/**
 * A full-width banner with its heading on it.
 *
 * The community directory's own header and a guild's front page are the same
 * shape: a 4:1 strip running the width of the content area, a title and a
 * subtitle over it, and a layout that stops being a strip on a phone. That
 * shape lives here once; the two callers differ only in what they hand it —
 * the directory its shipped artwork and its own copy, a guild its banner (or
 * the colour it picked instead), its name and description, and the two layout
 * choices its admin made.
 *
 * Nothing is applied to the picture itself beyond the fade the guild asked
 * for. The directory's artwork fades out along its bottom edge because that
 * fade is painted into the file; a guild's banner is shown as uploaded.
 *
 * A banner that is only a colour is a band, not a hero: it is sized by the
 * copy on it rather than by the viewport, because there is nothing in it to
 * see and a screen-height rectangle of one colour is just a wall.
 */

import { type CSSProperties, type ReactNode, useLayoutEffect, useRef, useState } from "react";

import { readableTextColor, readableTextShadow } from "@/lib/contrastColor";
import { cn } from "@/lib/utils";

/**
 * Widens an element from the padded, centred column a page is rendered in to
 * the whole content area beside the sidebar.
 *
 * How wide that area is depends on the shell around the page — which sidebars
 * are open, and which shell the page is being shown in — so it is measured
 * rather than restated as classes here, and measured again when it changes.
 * Until it has been, the classes on the element still take it out to the edges
 * of the column's padding, so nothing jumps.
 */
const useFullBleed = <T extends HTMLElement>() => {
  const ref = useRef<T>(null);
  const [style, setStyle] = useState<CSSProperties>();
  // How far in from each of the banner's edges the page's own content column
  // starts — exactly what the banner was widened by, back the other way.
  // Anything on the banner that should line up with the page below it (the
  // left-aligned copy, the badges in the corner) indents by these.
  const [inset, setInset] = useState({ left: 0, right: 0 });

  useLayoutEffect(() => {
    const element = ref.current;
    const column = element?.parentElement;
    const area = element?.closest("main")?.parentElement;
    if (!column || !area) return;

    const measure = () => {
      const columnBox = column.getBoundingClientRect();
      const areaBox = area.getBoundingClientRect();
      // Set from the column rather than from the element, whose own box is
      // what these values move.
      setStyle((current) =>
        current?.width === areaBox.width && current?.marginLeft === areaBox.left - columnBox.left
          ? current
          : {
              marginLeft: areaBox.left - columnBox.left,
              marginRight: 0,
              width: areaBox.width,
              maxWidth: "none",
            }
      );
      const left = columnBox.left - areaBox.left;
      const right = areaBox.right - columnBox.right;
      setInset((current) =>
        current.left === left && current.right === right ? current : { left, right }
      );
    };
    measure();

    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(area);
    observer.observe(column);
    return () => observer.disconnect();
  }, []);

  return { ref, style, inset };
};

export type PageBannerAlign = "center" | "left";
export type PageBannerFade = "none" | "weak" | "strong";

/**
 * A fade is a second grid row of `extend` pixels below the banner's own, and
 * exactly that much taken back off the banner's bottom margin.
 *
 * Adding and subtracting the same number is the whole trick: the copy does not
 * move, the page's next element does not move, and the space between them is
 * banner rather than nothing — so the tool rail and the table end up sitting
 * over a banner that is dissolving underneath them. The extra row is a fixed
 * track so that the artwork, which spans both, still sizes only the first one.
 *
 * `tail` is how far up from the very bottom the fade begins, and is always
 * `extend` plus the same small overlap: the dissolve covers the whole extra
 * row and reaches a couple of dozen pixels into the banner proper, never
 * further. That is what lets one pair of numbers serve both a tall photograph
 * and the short band a guild with no artwork gets — a percentage stop strong
 * enough to matter on the first would wash out the title on the second.
 */
const FADE_OVERLAP = 24;
const FADES: Record<Exclude<PageBannerFade, "none">, number> = {
  weak: 48,
  strong: 224,
};

export type PageBannerProps = {
  title: ReactNode;
  subtitle?: ReactNode;
  /** The picture to run behind the copy. */
  imageUrl?: string | null;
  /** What fills the banner where there is no picture. */
  color?: string | null;
  /**
   * What the copy is written in. A guild stores this, because artwork is not
   * one colour and what reads over a picture is not ours to guess. Left unset,
   * it is the best contrast against `color`.
   */
  textColor?: string | null;
  /** Where the copy sits across the banner. Centred unless asked otherwise. */
  align?: PageBannerAlign;
  /**
   * How far the banner dissolves into the page below it. Anything but `none`
   * extends the banner past where it would have ended and fades it out there,
   * so the page's own content rides over the tail.
   */
  fade?: PageBannerFade;
  /** Chips for the banner's top-right corner — a guild's roster and room counts. */
  badges?: ReactNode;
  /** Alt text for the picture; empty for artwork that says nothing. */
  imageAlt?: string;
  /**
   * Hold the copy at a dark neutral inside a halo of the artwork's own light,
   * instead of using `textColor`. For a fixed light-toned illustration the
   * theme changes under the words and the picture does not, so the halo is
   * what keeps the detail behind them visible.
   */
  haloOverImage?: boolean;
};

export function PageBanner({
  title,
  subtitle,
  imageUrl,
  color,
  textColor,
  align = "center",
  fade = "none",
  badges,
  imageAlt = "",
  haloOverImage = false,
}: PageBannerProps) {
  const banner = useFullBleed<HTMLDivElement>();
  const halo = !!imageUrl && haloOverImage;
  const ink = textColor ?? readableTextColor(color ?? "");
  const extend = fade === "none" ? 0 : FADES[fade];
  // Masking the ground rather than the whole banner is what keeps the fade off
  // the words: the copy is a sibling of this layer, not a child of it.
  const dissolve: CSSProperties = extend
    ? (() => {
        const gradient = `linear-gradient(to bottom, #000 calc(100% - ${extend + FADE_OVERLAP}px), transparent 100%)`;
        return { maskImage: gradient, WebkitMaskImage: gradient };
      })()
    : {};

  // It runs the full width of the content area rather than of the page: the
  // shell renders a page in a padded, centred column, and this is widened back
  // out to everything beside the sidebar.
  //
  // With a picture, from `lg` up the image is in flow, sharing a grid cell
  // with the copy, so the banner is as tall as whichever needs more room — the
  // image at its own proportions, with the copy over it, and a title that
  // wraps to more lines opens the banner up rather than running past it.
  //
  // Below that a 4:1 strip would be too short to hold a heading, so the image
  // is taken out of flow to fill a banner the copy sizes instead, over a
  // minimum that keeps a phone's close to square rather than a strip. There it
  // is matched to the banner's height and centred, so its width overhangs and
  // is clipped: what shows is the middle of the picture at something like its
  // own size, all of it top to bottom. Both are positioned, so the copy paints
  // over the image rather than under it.
  //
  // With only a colour there is no picture to give the banner a size, and none
  // to lose by keeping it short — so it is a band the copy sizes, at a smaller
  // type scale, rather than a hero.
  return (
    <div
      ref={banner.ref}
      style={{
        ...banner.style,
        // The extra row is a fixed track, so the artwork spanning both still
        // sizes only the first; the margin gives back exactly what it added.
        ...(extend ? { gridTemplateRows: `auto ${extend}px`, marginBottom: -extend } : null),
      }}
      className="relative -mx-4 -mt-4 grid overflow-hidden md:-mx-8 md:-mt-8"
    >
      {/* The ground: the fill, the artwork, and the fade over both. It spans
          the banner's row and the fade's, and stretches to them, so the image
          still gives the banner its height at `lg` exactly as it did when it
          was a child of the banner itself. */}
      <div
        style={{ ...(imageUrl ? null : { backgroundColor: color ?? undefined }), ...dissolve }}
        className={cn("relative col-start-1 row-start-1", extend && "row-span-2")}
      >
        {imageUrl ? (
          <img
            src={imageUrl}
            alt={imageAlt}
            className="absolute inset-y-0 left-1/2 h-full w-auto max-w-none -translate-x-1/2 lg:static lg:h-auto lg:w-full lg:max-w-full lg:translate-x-0"
          />
        ) : null}
      </div>
      <div
        // Left-aligned copy lines up with the page's own content rather than
        // with the banner's edge: the banner is pulled out to the full width
        // of the content area, and this puts the words back where the tool
        // rail and the table below them start. Centred copy is centred on the
        // whole banner, which is what being centred means. Until the measure
        // lands the class padding holds it, so nothing starts off-screen.
        style={
          align === "left" && banner.inset.left ? { paddingLeft: banner.inset.left } : undefined
        }
        className={cn(
          "relative col-start-1 row-start-1 flex flex-col justify-center gap-1 px-4 sm:gap-2 md:px-8",
          align === "left" ? "items-start text-left" : "items-center text-center",
          imageUrl
            ? "min-h-[85vw] py-10 sm:min-h-[45vw] md:min-h-[28vw] lg:min-h-0"
            : "min-h-28 py-6 sm:min-h-32 lg:min-h-36"
        )}
      >
        <h1
          className={cn(
            "text-balance font-black tracking-tight",
            imageUrl ? "text-4xl sm:text-5xl lg:text-6xl" : "text-2xl sm:text-3xl lg:text-4xl",
            halo &&
              "text-neutral-900 [text-shadow:0_0_10px_rgba(255,255,255,0.95),0_0_28px_rgba(255,255,255,0.8)]"
          )}
          // A shadow of the ink's opposite, so the words survive the patch of
          // artwork the guild's one text colour did not anticipate.
          style={halo ? undefined : { color: ink, textShadow: readableTextShadow(ink) }}
        >
          {title}
        </h1>
        {subtitle ? (
          <p
            className={cn(
              "max-w-2xl text-balance font-medium",
              imageUrl ? "text-base sm:text-lg lg:text-xl" : "text-sm sm:text-base",
              halo &&
                "text-neutral-800 [text-shadow:0_0_8px_rgba(255,255,255,0.95),0_0_20px_rgba(255,255,255,0.8)]"
            )}
            // Slightly softened against the fill, the way the halo variant is.
            style={
              halo ? undefined : { color: ink, opacity: 0.88, textShadow: readableTextShadow(ink) }
            }
          >
            {subtitle}
          </p>
        ) : null}
      </div>
      {/* The corner, not the copy: these say how big the guild is, which is
          about the banner rather than part of what it says. Held off the right
          edge by the same distance the page's own content is, so they line up
          with what is below them however wide the shell happens to be. */}
      {badges ? (
        <div
          style={banner.inset.right ? { right: banner.inset.right } : undefined}
          className="absolute top-4 right-4 z-10 flex flex-wrap items-center justify-end gap-2 md:top-6 md:right-8"
        >
          {badges}
        </div>
      ) : null}
      {/* The fade's own row. Nothing in it — the ground behind it is the whole
          point, and the page's next element is pulled back over it. */}
      {extend ? <div className="col-start-1 row-start-2" /> : null}
    </div>
  );
}
