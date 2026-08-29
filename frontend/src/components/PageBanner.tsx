/**
 * A full-width banner with its heading centred on it.
 *
 * The community directory's own header and a guild's front page are the same
 * shape: a 4:1 strip running the width of the content area, a title and a
 * subtitle centred over it, and a layout that stops being a strip on a phone.
 * That shape lives here once; the two callers differ only in what they hand it
 * — the directory its shipped artwork and its own copy, a guild its banner (or
 * the colour it picked instead) and its name and description.
 *
 * Nothing is applied to the picture itself. The directory's artwork fades out
 * along its bottom edge because that fade is painted into the file; a guild's
 * banner is shown as uploaded.
 *
 * A banner that is only a colour is a band, not a hero: it is sized by the
 * copy on it rather than by the viewport, because there is nothing in it to
 * see and a screen-height rectangle of one colour is just a wall.
 */

import { type CSSProperties, type ReactNode, useLayoutEffect, useRef, useState } from "react";

import { readableTextColor } from "@/lib/contrastColor";
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
    };
    measure();

    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(area);
    observer.observe(column);
    return () => observer.disconnect();
  }, []);

  return { ref, style };
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
  imageAlt = "",
  haloOverImage = false,
}: PageBannerProps) {
  const banner = useFullBleed<HTMLDivElement>();
  const halo = !!imageUrl && haloOverImage;
  const ink = textColor ?? readableTextColor(color ?? "");

  // It runs the full width of the content area rather than of the page: the
  // shell renders a page in a padded, centred column, and this is widened back
  // out to everything beside the sidebar.
  //
  // With a picture, from `lg` up the image is in flow, sharing a grid cell
  // with the copy, so the banner is as tall as whichever needs more room — the
  // image at its own proportions, with the copy centred on it, and a title
  // that wraps to more lines opens the banner up rather than running past it.
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
      style={{ ...banner.style, ...(imageUrl ? null : { backgroundColor: color ?? undefined }) }}
      className="relative -mx-4 -mt-4 grid overflow-hidden md:-mx-8 md:-mt-8"
    >
      {imageUrl ? (
        <img
          src={imageUrl}
          alt={imageAlt}
          className="absolute inset-y-0 left-1/2 col-start-1 row-start-1 h-full w-auto max-w-none -translate-x-1/2 lg:static lg:h-auto lg:w-full lg:max-w-full lg:translate-x-0 lg:self-start"
        />
      ) : null}
      <div
        className={cn(
          "relative col-start-1 row-start-1 flex flex-col items-center justify-center gap-1 px-4 text-center sm:gap-2 md:px-8",
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
          style={halo ? undefined : { color: ink }}
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
            style={halo ? undefined : { color: ink, opacity: 0.88 }}
          >
            {subtitle}
          </p>
        ) : null}
      </div>
    </div>
  );
}
