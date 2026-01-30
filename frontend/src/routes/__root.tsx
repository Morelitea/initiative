import { Suspense } from "react";
import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";

import type { RouterContext } from "@/router";
import { useInterfaceColors } from "@/hooks/useInterfaceColors";
import { useColorTheme } from "@/hooks/useColorTheme";
import { useSafeArea } from "@/hooks/useSafeArea";
import { useDeepLinks } from "@/hooks/useDeepLinks";

/**
 * Loading fallback for lazy-loaded pages.
 */
const PageLoader = () => (
  <div className="flex items-center justify-center py-20">
    <Loader2 className="text-muted-foreground h-8 w-8 animate-spin" />
  </div>
);

/**
 * Root component that handles global hooks.
 */
const RootComponent = () => {
  // Global hooks
  useInterfaceColors();
  useColorTheme();
  useSafeArea();
  useDeepLinks();

  return (
    <Suspense fallback={<PageLoader />}>
      <Outlet />
    </Suspense>
  );
};

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootComponent,
});
