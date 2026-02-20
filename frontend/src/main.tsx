import "./styles.css";
import "./i18n";

import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import React, { Suspense } from "react";
import ReactDOM from "react-dom/client";
import { Toaster } from "sonner";

import { Capacitor } from "@capacitor/core";

import { AuthProvider, useAuth } from "@/hooks/useAuth";
import { GuildProvider, useGuilds } from "@/hooks/useGuilds";
import { ServerProvider, useServer } from "@/hooks/useServer";
import { ThemeProvider } from "@/hooks/useTheme";
import { setApiBaseUrl } from "@/api/client";
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
      <Toaster position="bottom-center" />
    </>
  );
};

async function bootstrap() {
  await initStorage();

  // On native, set the API base URL immediately from storage so requests
  // reach the real backend before React effects run (avoids race condition
  // where child provider effects fire before ServerProvider's useEffect).
  if (Capacitor.isNativePlatform()) {
    const storedUrl = getStoredServerUrl();
    if (storedUrl) {
      setApiBaseUrl(storedUrl);
    }
  }

  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>
      <Suspense fallback={null}>
        <ThemeProvider>
          <ServerProvider>
            <QueryClientProvider client={queryClient}>
              <AuthProvider>
                <GuildProvider>
                  <InnerApp />
                </GuildProvider>
              </AuthProvider>
            </QueryClientProvider>
          </ServerProvider>
        </ThemeProvider>
      </Suspense>
    </React.StrictMode>
  );

  if (import.meta.env.PROD) {
    registerServiceWorker();
  }
}

void bootstrap();
