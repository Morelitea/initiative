import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { lazy, Suspense } from "react";

import { StepUpDialog } from "@/components/auth/StepUpDialog";
import { useColorTheme } from "@/hooks/useColorTheme";
import { useDeepLinks } from "@/hooks/useDeepLinks";
import { useInterfaceColors } from "@/hooks/useInterfaceColors";
import { useSafeArea } from "@/hooks/useSafeArea";
import type { RouterContext } from "@/router";

const TanStackRouterDevtools = import.meta.env.DEV
  ? lazy(() =>
      import("@tanstack/react-router-devtools").then((mod) => ({
        default: mod.TanStackRouterDevtools,
      }))
    )
  : () => null;

/**
 * Loading fallback for lazy-loaded pages.
 */
const PageLoader = () => (
  <div className="flex items-center justify-center py-20">
    <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
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
    <>
      <Suspense fallback={<PageLoader />}>
        <Outlet />
      </Suspense>
      <StepUpDialog />
      <Suspense>
        <TanStackRouterDevtools position="bottom-right" />
      </Suspense>
    </>
  );
};

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootComponent,
});
