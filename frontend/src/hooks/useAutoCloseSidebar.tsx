import { useLocation } from "@tanstack/react-router";
import { useEffect } from "react";

import { useSidebar } from "@/components/ui/sidebar";

/**
 * Automatically closes the sidebar on mobile devices after navigation.
 * This improves mobile UX by preventing the sidebar from staying open
 * and obscuring content after the user navigates to a new page.
 *
 * A navigation can opt out via `suppressNextAutoClose()` (e.g. switching
 * guilds, which navigates but should leave the sidebar open).
 */
export const useAutoCloseSidebar = () => {
  const location = useLocation();
  const { setOpenMobile, isMobile, consumeAutoCloseSuppression } = useSidebar();

  useEffect(() => {
    // Always consume so a suppression set on desktop can't leak to a later
    // mobile navigation.
    const suppressed = consumeAutoCloseSuppression();
    if (isMobile && !suppressed) {
      setOpenMobile(false);
    }
  }, [location.pathname, isMobile, setOpenMobile, consumeAutoCloseSuppression]);
};
