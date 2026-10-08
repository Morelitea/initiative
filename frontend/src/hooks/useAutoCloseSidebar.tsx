import { useLocation } from "@tanstack/react-router";
import { useEffect, useRef } from "react";

import { useSidebar } from "@/components/ui/sidebar";

/**
 * Automatically closes the sidebar on mobile devices after navigation.
 * This improves mobile UX by preventing the sidebar from staying open
 * and obscuring content after the user navigates to a new page.
 *
 * A navigation can opt out via `suppressNextAutoClose()` (e.g. switching
 * communities, which navigates but should leave the sidebar open).
 *
 * Only a change of path counts. React runs this effect again whenever the
 * tree around it is shown after a suspension — a dialog opened from the
 * sidebar that loads its translations, say — and that is not a navigation.
 */
export const useAutoCloseSidebar = () => {
  const location = useLocation();
  const { setOpenMobile, isMobile, consumeAutoCloseSuppression } = useSidebar();
  const lastPath = useRef(location.pathname);

  useEffect(() => {
    if (lastPath.current === location.pathname) return;
    lastPath.current = location.pathname;
    // Always consume so a suppression set on desktop can't leak to a later
    // mobile navigation.
    const suppressed = consumeAutoCloseSuppression();
    if (isMobile && !suppressed) {
      setOpenMobile(false);
    }
  }, [location.pathname, isMobile, setOpenMobile, consumeAutoCloseSuppression]);
};
