import "./styles.css";
import "./i18n";

import { Capacitor } from "@capacitor/core";
import { SplashScreen } from "@capacitor/splash-screen";
import { CapacitorUpdater } from "@capgo/capacitor-updater";
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import React, { Suspense } from "react";
import ReactDOM from "react-dom/client";

import { setApiBaseUrl } from "@/api/client";
import { TaskCompletionEffectHost } from "@/components/effects/TaskCompletionEffectHost";
import { AuthProvider, useAuth } from "@/hooks/useAuth";
import { GuildProvider, useGuilds } from "@/hooks/useGuilds";
import { KeepScreenAwakeProvider } from "@/hooks/useKeepScreenAwake";
import { ServerProvider, useServer } from "@/hooks/useServer";
import { ThemeProvider } from "@/hooks/useTheme";
import { queryClient } from "@/lib/queryClient";
import { getStoredServerUrl } from "@/lib/serverStorage";
import { initStorage } from "@/lib/storage";
import { router } from "@/router";
import { registerServiceWorker } from "@/serviceWorkerRegistration";

/**
 * Inner app component that provides router context from hooks.
 * Must be inside all providers to access their contexts.
 */
const InnerApp = () => {
  const auth = useAuth();
  const guilds = useGuilds();
  const server = useServer();

  return (
    <>
      <RouterProvider
        router={router}
        context={{
          queryClient,
          auth,
          guilds,
          server,
        }}
      />
      <TaskCompletionEffectHost />
    </>
  );
};

async function bootstrap() {
  await initStorage();

  // On native, set the API base URL immediately from storage so requests
  // reach the real backend before React effects run (avoids race condition
  // where child provider effects fire before ServerProvider's useEffect).
  if (Capacitor.isNativePlatform()) {
    // Confirm this web bundle booted so the OTA updater doesn't roll it back. If an applied
    // bundle never reaches this point within appReadyTimeout, Capgo reverts to the last-good
    // bundle on next launch (see capacitor.config.ts → CapacitorUpdater). Best-effort.
    try {
      await CapacitorUpdater.notifyAppReady();
    } catch (error) {
      console.debug("notifyAppReady failed (updater unavailable):", error);
    }

    // Drop the native splash now that this bundle is alive. It is kept up (launchAutoHide off)
    // to cover both cold start and the OTA bundle swap that useNativeUpdate raises before
    // CapacitorUpdater.set() reloads the WebView. Always hide it — even if notifyAppReady threw
    // above — so a failure there can't strand the user on the splash. Best-effort.
    try {
      await SplashScreen.hide();
    } catch (error) {
      console.debug("SplashScreen.hide failed (plugin unavailable):", error);
    }

    const storedUrl = getStoredServerUrl();
    if (storedUrl) {
      setApiBaseUrl(storedUrl);
    }
  }

  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>
      <Suspense fallback={null}>
        <ThemeProvider>
          <KeepScreenAwakeProvider>
            <ServerProvider>
              <QueryClientProvider client={queryClient}>
                <AuthProvider>
                  <GuildProvider>
                    <InnerApp />
                  </GuildProvider>
                </AuthProvider>
              </QueryClientProvider>
            </ServerProvider>
          </KeepScreenAwakeProvider>
        </ThemeProvider>
      </Suspense>
    </React.StrictMode>
  );

  if (import.meta.env.PROD) {
    registerServiceWorker();
  }
}

void bootstrap();
