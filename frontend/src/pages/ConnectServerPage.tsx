import { useRouter } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { LogoIcon } from "@/components/LogoIcon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { useServer } from "@/hooks/useServer";

export const ConnectServerPage = () => {
  const { t } = useTranslation(["auth", "common"]);
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
        backgroundImage: `url(${isDark ? "./images/hexWhite.svg" : "./images/hexBlack.svg"})`,
        backgroundPosition: "center",
        backgroundBlendMode: "screen",
        backgroundSize: "67px 116px",
      }}
    >
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-muted/60 px-4 py-12">
        <div className="flex items-center gap-3 font-semibold text-3xl text-primary tracking-tight">
          <LogoIcon className="h-12 w-12" aria-hidden="true" focusable="false" />
          <span className="pride-wordmark">{t("common:appName")}</span>
        </div>
        <Card className="w-full max-w-md shadow-lg">
          <CardHeader>
            <CardTitle>{t("connectServer.title")}</CardTitle>
            <CardDescription>{t("connectServer.subtitle")}</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleSubmit}>
              {/* Initiative Cloud is not open yet, so self-hosted is the only choice. */}
              <RadioGroup
                defaultValue="selfHosted"
                aria-label={t("connectServer.whereLabel")}
                className="gap-3"
              >
                {(["cloud", "selfHosted"] as const).map((where) => (
                  <Label
                    key={where}
                    htmlFor={`connect-${where}`}
                    className="flex cursor-pointer items-start gap-3 rounded-xl border-2 bg-card p-3 font-normal transition-colors hover:border-primary/40 has-[:disabled]:cursor-not-allowed has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-primary/5 has-[:disabled]:opacity-60 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring has-[:disabled]:hover:border-border"
                  >
                    <span className="min-w-0 flex-1 space-y-1">
                      <span className="flex items-center gap-2 font-semibold">
                        {t(`connectServer.${where}`)}
                        {where === "cloud" ? (
                          <Badge variant="secondary">{t("connectServer.cloudSoon")}</Badge>
                        ) : null}
                      </span>
                      <span className="block text-muted-foreground text-sm">
                        {t(`connectServer.${where}Hint`)}
                      </span>
                    </span>
                    <RadioGroupItem
                      id={`connect-${where}`}
                      value={where}
                      disabled={where === "cloud"}
                    />
                  </Label>
                ))}
              </RadioGroup>
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
