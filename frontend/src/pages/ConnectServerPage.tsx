import { FormEvent, useState } from "react";
import { useRouter } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LogoIcon } from "@/components/LogoIcon";
import { useServer } from "@/hooks/useServer";

export const ConnectServerPage = () => {
  const { t } = useTranslation("auth");
  const router = useRouter();
  const { setServerUrl, testServerConnection } = useServer();
  const [serverUrlInput, setServerUrlInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    const trimmedUrl = serverUrlInput.trim();
    if (!trimmedUrl) {
      setError(t("connectServer.emptyUrl"));
      setSubmitting(false);
      return;
    }

    try {
      // Test the connection first
      const result = await testServerConnection(trimmedUrl);
      if (!result.valid) {
        setError(result.error ?? t("connectServer.defaultConnectError"));
        setSubmitting(false);
        return;
      }

      // Connection successful, save the URL
      await setServerUrl(trimmedUrl);

      // Navigate to login with search param indicating we just connected
      router.navigate({ to: "/login", search: { connected: "1" }, replace: true });
    } catch (err) {
      console.error(err);
      setError(t("connectServer.unexpectedError"));
    } finally {
      setSubmitting(false);
    }
  };

  const isDark = document.documentElement.classList.contains("dark");

  return (
    <div
      style={{
        backgroundImage: `url(${isDark ? "./images/gridWhite.svg" : "./images/gridBlack.svg"})`,
        backgroundPosition: "center",
        backgroundBlendMode: "screen",
        backgroundSize: "96px 96px",
      }}
    >
      <div className="bg-muted/60 flex min-h-screen flex-col items-center justify-center gap-3 px-4 py-12">
        <div className="text-primary flex items-center gap-3 text-3xl font-semibold tracking-tight">
          <LogoIcon className="h-12 w-12" aria-hidden="true" focusable="false" />
          {t("common:appName")}
        </div>
        <Card className="w-full max-w-md shadow-lg">
          <CardHeader>
            <CardTitle>{t("connectServer.title")}</CardTitle>
            <CardDescription>{t("connectServer.subtitle")}</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleSubmit}>
              <div className="space-y-2">
                <Label htmlFor="serverUrl">{t("connectServer.serverUrlLabel")}</Label>
                <Input
                  id="serverUrl"
                  name="serverUrl"
                  type="url"
                  placeholder={t("connectServer.serverUrlPlaceholder")}
                  value={serverUrlInput}
                  onChange={(event) => setServerUrlInput(event.target.value)}
                  autoCapitalize="none"
                  autoCorrect="off"
                  required
                />
                <p className="text-muted-foreground text-xs">{t("connectServer.serverUrlHelp")}</p>
              </div>
              <Button className="w-full" type="submit" disabled={submitting}>
                {submitting ? t("connectServer.submitting") : t("connectServer.submit")}
              </Button>
              {error ? <p className="text-destructive text-sm">{error}</p> : null}
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};
