import { type Decoration, FRAME_APERTURE_INSET } from "@/lib/profileDecorations";
import { cn } from "@/lib/utils";

/**
 * One decoration, drawn the way its slot is worn.
 *
 * The three slots want three different shapes — a banner is a strip, a frame is
 * a ring around a face, a badge is a mark beside a name — and every surface
 * that lists decorations wants the same three. So they are settled once here,
 * and the picker, the store and the pack list only choose how wide to make it.
 *
 * A frame is artwork with a hole in it, which on its own reads as a ring around
 * nothing; the muted disc stands in for the picture so the shape reads.
 */
export const DecorationSwatch = ({
  decoration,
  className,
}: {
  decoration: Decoration;
  className?: string;
}) => {
  if (decoration.kind === "banner") {
    return (
      <span
        className={cn("block h-10 w-full rounded-sm bg-center bg-cover", className)}
        style={{ backgroundImage: `url(${decoration.src})` }}
      />
    );
  }

  if (decoration.kind === "frame") {
    return (
      <span className={cn("relative block size-10", className)}>
        <span
          className="absolute rounded-full bg-muted-foreground/20"
          style={{ inset: FRAME_APERTURE_INSET }}
        />
        <img
          src={decoration.src}
          alt=""
          aria-hidden="true"
          className="absolute inset-0 size-full"
        />
      </span>
    );
  }

  return <img src={decoration.src} alt="" aria-hidden="true" className={cn("size-8", className)} />;
};
