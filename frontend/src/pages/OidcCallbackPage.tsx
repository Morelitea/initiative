import { useEffect, useState } from "react";
import { useRouter, useSearch } from "@tanstack/react-router";
import { Browser } from "@capacitor/browser";
import { useTranslation } from "react-i18next";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";
import { useServer } from "@/hooks/useServer";

export const OidcCallbackPage = () => {
  const { t } = useTranslation("auth");
  const searchParams = useSearch({ strict: false }) as {
    token?: string;
    token_type?: string;
    error?: string;
  };
  const router = useRouter();
  const { completeOidcLogin } = useAuth();
  const { isNativePlatform } = useServer();
  const [status, setStatus] = useState(t("oidcCallback.finishing"));

  useEffect(() => {
    const error = searchParams.error;
    if (error) {
      setStatus(t("oidcCallback.failedWithError", { error }));
      return;
    }
    const run = async () => {
      try {
        // token is present for native (device_token); undefined for web (cookie was set by backend)
        await completeOidcLogin(searchParams.token, searchParams.token_type === "device_token");
        // Close the browser on mobile before navigating
        if (isNativePlatform) {
          try {
            await Browser.close();
          } catch {
            // Browser may already be closed, ignore
          }
        }
        router.navigate({ to: "/", replace: true });
      } catch (err) {
        console.error(err);
        setStatus(t("oidcCallback.error"));
      }
    };
    void run();
  }, [completeOidcLogin, isNativePlatform, router, searchParams, t]);

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <Card className="w-full max-w-md shadow-sm">
        <CardHeader>
          <CardTitle>{t("oidcCallback.title")}</CardTitle>
          <CardDescription>{t("oidcCallback.subtitle")}</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-sm">{status}</p>
        </CardContent>
      </Card>
    </div>
  );
};
