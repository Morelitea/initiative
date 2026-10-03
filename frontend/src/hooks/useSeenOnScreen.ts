import { useEffect, useRef, useState } from "react";

/**
 * Whether an element has come on screen yet, for a card that reads its
 * preview only once somebody could see it. Stays true once seen, so scrolling
 * back past it reads nothing again.
 */
export const useSeenOnScreen = <T extends Element>() => {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || seen) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry?.isIntersecting) {
        setSeen(true);
        observer.disconnect();
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [seen]);

  return { ref, seen };
};
