import { useEffect } from "react";
import { App, URLOpenListenerEvent } from "@capacitor/app";
import { useRouter } from "@tanstack/react-router";
import { useServer } from "./useServer";

/**
 * Hook to handle deep links on native platforms.
 * Listens for app URL open events and routes them appropriately.
 */
export function useDeepLinks() {
  const router = useRouter();
  const { isNativePlatform } = useServer();

  useEffect(() => {
    if (!isNativePlatform) return;

    const listener = App.addListener("appUrlOpen", (event: URLOpenListenerEvent) => {
      try {
        const url = new URL(event.url);

        // Handle OIDC callback: initiative://oidc/callback?token=xxx
        // The URL can come as initiative://oidc/callback or initiative://oidc
        if (
          url.pathname === "/oidc/callback" ||
          url.pathname === "/callback" ||
          url.host === "oidc"
        ) {
          const token = url.searchParams.get("token");
          const error = url.searchParams.get("error");
          if (token) {
            const token_type = url.searchParams.get("token_type");
            router.navigate({
              to: "/oidc/callback",
              search: token_type ? { token, token_type } : { token },
              replace: true,
            });
          } else if (error) {
            router.navigate({
              to: "/oidc/callback",
              search: { error },
              replace: true,
            });
          }
        }
      } catch (err) {
        console.error("Failed to parse deep link URL:", err);
      }
    });

    return () => {
      listener.then((l) => l.remove());
    };
  }, [isNativePlatform, router]);
}
