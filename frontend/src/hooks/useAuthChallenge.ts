import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Hold the first sign-in challenge the API client announces on `eventName`.
 *
 * Both step-up dialogs work the same way: a refused request dispatches a
 * window event describing what the community wants, and the dialog that
 * answers it is mounted once at the root rather than per page. A single page
 * load can produce many refusals at once — every query it fired — and they all
 * name the same requirement, so the first one wins and the rest are ignored
 * until it is cleared.
 *
 * `accept` decides whether a detail is usable; an event missing what the
 * dialog needs opens nothing. It is read through a ref so that passing an
 * inline predicate doesn't resubscribe the listener on every render.
 */
export const useAuthChallenge = <T>(
  eventName: string,
  accept: (detail: T | undefined) => boolean,
  { listen = true }: { listen?: boolean } = {}
) => {
  const [challenge, setChallenge] = useState<T | null>(null);
  const acceptRef = useRef(accept);
  acceptRef.current = accept;

  useEffect(() => {
    if (!listen) {
      return;
    }
    const onChallenge = (event: Event) => {
      const detail = (event as CustomEvent<T>).detail;
      if (acceptRef.current(detail)) {
        setChallenge((current) => current ?? detail);
      }
    };
    window.addEventListener(eventName, onChallenge);
    return () => window.removeEventListener(eventName, onChallenge);
  }, [eventName, listen]);

  const clear = useCallback(() => setChallenge(null), []);

  return { challenge, clear, open: challenge !== null };
};
