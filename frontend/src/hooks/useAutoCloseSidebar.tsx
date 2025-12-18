import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { useSidebar } from "@/components/ui/sidebar";

/**
 * Automatically closes the sidebar on mobile devices after navigation.
 * This improves mobile UX by preventing the sidebar from staying open
 * and obscuring content after the user navigates to a new page.
 */
export const useAutoCloseSidebar = () => {
  const location = useLocation();
  const { setOpenMobile, isMobile } = useSidebar();

  useEffect(() => {
    if (isMobile) {
      setOpenMobile(false);
    }
  }, [location.pathname, isMobile, setOpenMobile]);
};
