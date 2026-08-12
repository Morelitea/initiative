import { createFileRoute, Outlet, redirect, useSearch } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";

import { NativeUpdateRequiredDialog } from "@/components/NativeUpdateRequiredDialog";
import { VersionDialog } from "@/components/VersionDialog";
import { useNativeUpdate } from "@/hooks/useNativeUpdate";
import { useServer } from "@/hooks/useServer";

const FullScreenLoader = () => (
  <div className="flex min-h-screen items-center justify-center">
    <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
  </div>
);

/**
 * Layout route that requires a server to be configured on native platforms.
 * On web, this passes through. On mobile without a configured server, redirects to /connect.
 */
export const Route = createFileRoute("/_serverRequired")({
  beforeLoad: ({ context, search }) => {
    const { server } = context;
    const justConnected = (search as { connected?: string })?.connected === "1";

    // If server context is ready and we're on native without a server, redirect
    // Skip if we just connected (search param indicates state is updating)
    if (
      !justConnected &&
      !server?.loading &&
      server?.isNativePlatform &&
      !server.isServerConfigured
    ) {
      throw redirect({ to: "/connect" });
    }
  },
  component: ServerRequiredLayout,
});

function ServerRequiredLayout() {
  const { loading, isNativePlatform, isServerConfigured } = useServer();
  const search = useSearch({ strict: false }) as { connected?: string };
  // OTA live updates (native only). Mounted here — once a server is configured but before
  // auth is required — so a fresh install can update its web bundle even from the login screen.
  const {
    updateReady,
    applyUpdate,
    dismissUpdate,
    nativeUpdateRequired,
    dismissNativeUpdateRequired,
  } = useNativeUpdate();

  // Check if we just connected from the connect page (search param passed via navigation)
  const justConnected = search?.connected === "1";

  // Show loading state while server context initializes
  if (loading) {
    return <FullScreenLoader />;
  }

  // On native with no server configured (and we didn't just connect), the
  // redirect belongs to `beforeLoad` above, which re-runs once the server
  // context settles (``useRouteGuardSync``). Hold the loader until it lands
  // rather than redirecting from the render path — a rendered `<Navigate>`
  // re-navigates on every render and stops only because this layout unmounts.
  if (isNativePlatform && !isServerConfigured && !justConnected) {
    return <FullScreenLoader />;
  }

  return (
    <>
      <Outlet />
      <VersionDialog
        mode="update"
        open={updateReady.show}
        currentVersion={updateReady.version}
        newVersion={updateReady.version}
        onClose={dismissUpdate}
        onReload={() => void applyUpdate()}
      />
      <NativeUpdateRequiredDialog
        open={nativeUpdateRequired.show}
        version={nativeUpdateRequired.version}
        onClose={dismissNativeUpdateRequired}
      />
    </>
  );
}
