import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { LazyImage } from "@/components/shared/LazyImage";
import { Lightbox, type LightboxItem } from "@/components/shared/Lightbox";
import { cn } from "@/lib/utils";

interface Picture {
  src: string;
  alt: string;
}

interface Scope {
  register: (element: HTMLElement, picture: Picture) => () => void;
  open: (element: HTMLElement) => void;
}

const ScopeContext = createContext<Scope | null>(null);

/** Set by a rendered link: a picture inside one is what the link opens, so
 *  the link keeps the click. */
const InLinkContext = createContext(false);

export const InLink = ({ children }: { children: ReactNode }) => (
  <InLinkContext value>{children}</InLinkContext>
);

const inReadingOrder = ([a]: [Node, Picture], [b]: [Node, Picture]) =>
  a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;

/**
 * One block of rendered prose whose pictures open full size. Every
 * `ProseImage` inside it pages with the others, in the order they are read,
 * so a description with five screenshots is one lightbox rather than five.
 */
export const ImageLightboxScope = ({ children }: { children: ReactNode }) => {
  const pictures = useRef(new Map<HTMLElement, Picture>());
  const [items, setItems] = useState<LightboxItem[]>([]);
  const [index, setIndex] = useState(0);
  const [open, setOpen] = useState(false);

  const scope = useMemo<Scope>(
    () => ({
      register: (element, picture) => {
        pictures.current.set(element, picture);
        return () => {
          pictures.current.delete(element);
        };
      },
      open: (element) => {
        const ordered = [...pictures.current].sort(inReadingOrder);
        setItems(ordered.map(([, picture], position) => ({ id: position, ...picture })));
        setIndex(
          Math.max(
            0,
            ordered.findIndex(([each]) => each === element)
          )
        );
        setOpen(true);
      },
    }),
    []
  );

  return (
    <ScopeContext value={scope}>
      {children}
      <Lightbox
        open={open}
        onOpenChange={setOpen}
        items={items}
        index={index}
        onIndexChange={setIndex}
      />
    </ScopeContext>
  );
};

interface ProseImageProps {
  src: string;
  alt?: string;
  title?: string;
  /** The picture itself — its size cap, border, corners. */
  className?: string;
}

/**
 * A picture in rendered prose. It loads as it nears the screen and fades in,
 * as a gallery's do, and inside an `ImageLightboxScope` it opens full size.
 * Outside a scope, or inside a link, it is just the picture.
 *
 * Its size is not known ahead, so no space is reserved: it keeps its own
 * width, capped at the column's, rather than being stretched to fill it.
 */
export const ProseImage = ({ src, alt = "", title, className }: ProseImageProps) => {
  const { t } = useTranslation("common");
  const scope = useContext(ScopeContext);
  const inLink = useContext(InLinkContext);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const register = scope?.register;

  const ref = useCallback(
    (button: HTMLButtonElement | null) => {
      buttonRef.current = button;
      return button && register ? register(button, { src, alt }) : undefined;
    },
    [register, src, alt]
  );

  const picture = (
    <LazyImage
      src={src}
      alt={alt}
      title={title}
      className="inline-block max-w-full bg-transparent align-bottom"
      imgClassName={cn("h-auto w-auto max-w-full object-contain", className)}
    />
  );

  if (!scope || inLink) return picture;

  return (
    <button
      ref={ref}
      type="button"
      aria-label={alt ? t("lightbox.openNamed", { name: alt }) : t("lightbox.open")}
      onClick={() => buttonRef.current && scope.open(buttonRef.current)}
      className="inline-block max-w-full cursor-zoom-in rounded-md align-bottom focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {picture}
    </button>
  );
};
