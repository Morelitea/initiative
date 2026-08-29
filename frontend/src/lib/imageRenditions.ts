/**
 * Preparing an uploaded picture for storage.
 *
 * Someone picks one file. What the server stores are fixed renditions — a
 * square guild icon or profile picture, and a guild banner in two sizes
 * because its card appears up to sixty times on a directory page and its
 * front-page version is a third of a megabyte. Producing those here rather
 * than on the server means nobody is asked to prepare two files, and the
 * backend needs no image decoder in its request path; it still checks format,
 * weight, and shape on what arrives.
 *
 * The specs mirror ``app/models/platform/guild_image.py`` and
 * ``app/models/platform/user_avatar.py``. Both sides check against them, so a
 * change is two edits — the server's is the one that decides.
 */

/** What one stored rendition must be. */
export type ImageSpec = {
  width: number;
  height: number;
  maxBytes: number;
};

export const GUILD_ICON: ImageSpec = { width: 256, height: 256, maxBytes: 64 * 1024 };
/** A profile picture. Square, and the same weight as a guild icon: both are
 *  shown at 24-40px in lists and around 128px on their own settings page. */
export const AVATAR: ImageSpec = { width: 256, height: 256, maxBytes: 64 * 1024 };
export const GUILD_BANNER_CARD: ImageSpec = {
  width: 1040,
  height: 260,
  maxBytes: 60 * 1024,
};
export const GUILD_BANNER_FULL: ImageSpec = {
  width: 2400,
  height: 600,
  maxBytes: 350 * 1024,
};

/** The largest file we will read at all, before any of it is decoded. */
export const MAX_SOURCE_BYTES = 12 * 1024 * 1024;

export class ImageRenditionError extends Error {
  constructor(readonly code: "notAnImage" | "tooLarge" | "unreadable") {
    super(code);
  }
}

/**
 * Quality ladder, tried highest first: the first rendering that fits the
 * spec's weight is the one used. A banner is a photograph often enough that a
 * single fixed quality either wastes bytes or smears it.
 */
const QUALITY_STEPS = [0.9, 0.82, 0.74, 0.66, 0.58, 0.5, 0.4];

async function loadBitmap(file: File): Promise<ImageBitmap | HTMLImageElement> {
  if (typeof createImageBitmap === "function") {
    try {
      return await createImageBitmap(file);
    } catch {
      throw new ImageRenditionError("notAnImage");
    }
  }
  // Test environments and older WebViews: go through an <img> instead.
  const url = URL.createObjectURL(file);
  try {
    return await new Promise<HTMLImageElement>((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new ImageRenditionError("notAnImage"));
      image.src = url;
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}

/**
 * Draw ``source`` to fill ``spec``'s frame, cropping whatever overhangs.
 *
 * Cover rather than fit: a banner with letterboxing baked into it is a banner
 * that looks broken on the page, and the frame's proportions are the ones the
 * layout is built around. The middle of the picture is what survives.
 */
function drawCover(
  source: CanvasImageSource & { width: number; height: number },
  spec: ImageSpec
): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = spec.width;
  canvas.height = spec.height;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new ImageRenditionError("unreadable");
  }
  const scale = Math.max(spec.width / source.width, spec.height / source.height);
  const width = source.width * scale;
  const height = source.height * scale;
  context.imageSmoothingQuality = "high";
  context.drawImage(source, (spec.width - width) / 2, (spec.height - height) / 2, width, height);
  return canvas;
}

function toBlob(canvas: HTMLCanvasElement, type: string, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

async function encode(canvas: HTMLCanvasElement, spec: ImageSpec): Promise<File> {
  // WebP for the weight; PNG only if this browser cannot produce WebP, in
  // which case the ladder below is what keeps it inside the cap.
  for (const type of ["image/webp", "image/png"]) {
    for (const quality of QUALITY_STEPS) {
      const blob = await toBlob(canvas, type, quality);
      if (!blob || blob.type !== type) break; // this format isn't available
      if (blob.size <= spec.maxBytes) {
        const extension = type === "image/webp" ? "webp" : "png";
        return new File([blob], `image.${extension}`, { type });
      }
    }
  }
  throw new ImageRenditionError("tooLarge");
}

async function render(file: File, specs: ImageSpec[]): Promise<File[]> {
  if (!file.type.startsWith("image/")) {
    throw new ImageRenditionError("notAnImage");
  }
  if (file.size > MAX_SOURCE_BYTES) {
    throw new ImageRenditionError("tooLarge");
  }
  const source = await loadBitmap(file);
  try {
    const out: File[] = [];
    for (const spec of specs) {
      out.push(await encode(drawCover(source, spec), spec));
    }
    return out;
  } finally {
    if ("close" in source) source.close();
  }
}

/** One square icon from whatever the admin picked. */
export async function renderGuildIcon(file: File): Promise<File> {
  const [icon] = await render(file, [GUILD_ICON]);
  return icon;
}

/** The two banner renditions, in the order the endpoint takes them. */
export async function renderGuildBanner(file: File): Promise<{ full: File; card: File }> {
  const [full, card] = await render(file, [GUILD_BANNER_FULL, GUILD_BANNER_CARD]);
  return { full, card };
}

/** One square picture of a person from whatever they picked. */
export async function renderAvatar(file: File): Promise<File> {
  const [avatar] = await render(file, [AVATAR]);
  return avatar;
}
