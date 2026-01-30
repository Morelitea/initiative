import "./styles.css";

import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import React from "react";
import ReactDOM from "react-dom/client";
import { Toaster } from "sonner";

import { AuthProvider, useAuth } from "@/hooks/useAuth";
import { GuildProvider, useGuilds } from "@/hooks/useGuilds";
import { ServerProvider, useServer } from "@/hooks/useServer";
import { ThemeProvider } from "@/hooks/useTheme";
import { queryClient } from "@/lib/queryClient";
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

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
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
  </React.StrictMode>
);

if (import.meta.env.PROD) {
  registerServiceWorker();
}
