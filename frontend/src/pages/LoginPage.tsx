import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useRouter, useSearch } from "@tanstack/react-router";
import { Device } from "@capacitor/device";
import { Browser } from "@capacitor/browser";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/hooks/useAuth";
import { useServer } from "@/hooks/useServer";
import { LogoIcon } from "@/components/LogoIcon";
import { RegisterPage } from "./RegisterPage";

export const LoginPage = () => {
  const { t } = useTranslation(["auth", "common"]);
  const router = useRouter();
  const searchParams = useSearch({ strict: false }) as { invite_code?: string };
  const { login } = useAuth();
  const { isNativePlatform, isServerConfigured, getServerHostname, clearServerUrl, serverUrl } =
    useServer();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [oidcLoginUrl, setOidcLoginUrl] = useState<string | null>(null);
  const [oidcProviderName, setOidcProviderName] = useState<string | null>(null);
  const [bootstrapStatus, setBootstrapStatus] = useState<"loading" | "required" | "ready">(
    "loading"
  );
  const inviteCodeParam = useMemo(() => {
    const code = searchParams.invite_code;
    return code && code.trim().length > 0 ? code.trim() : null;
  }, [searchParams]);

  // Fetch OIDC status
  useEffect(() => {
    const fetchOidcStatus = async () => {
      try {
        const response = await apiClient.get<{
          enabled: boolean;
          login_url?: string;
          provider_name?: string;
        }>("/auth/oidc/status");
        if (response.data.enabled && response.data.login_url) {
          setOidcLoginUrl(response.data.login_url);
          setOidcProviderName(response.data.provider_name ?? null);
        } else {
          setOidcLoginUrl(null);
          setOidcProviderName(null);
        }
      } catch {
        setOidcLoginUrl(null);
        setOidcProviderName(null);
      }
    };
    void fetchOidcStatus();
  }, []);

  // Fetch bootstrap status
  useEffect(() => {
    const fetchBootstrapStatus = async () => {
      try {
        const response = await apiClient.get<{ has_users: boolean }>("/auth/bootstrap");
        setBootstrapStatus(response.data.has_users ? "ready" : "required");
      } catch {
        setBootstrapStatus("ready");
      }
    };
    void fetchBootstrapStatus();
  }, [isServerConfigured]);

  const handleChangeServer = () => {
    clearServerUrl();
    router.navigate({ to: "/connect", replace: true });
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      let deviceName: string | undefined;
      if (isNativePlatform) {
        try {
          const info = await Device.getInfo();
          deviceName = info.name || info.model || "Mobile Device";
        } catch {
          deviceName = "Mobile Device";
        }
      }
      await login({ email: email.toLowerCase().trim(), password, deviceName });
      if (inviteCodeParam) {
        router.navigate({
          to: "/invite/$code",
          params: { code: encodeURIComponent(inviteCodeParam) },
          search: { authenticated: "1" },
          replace: true,
        });
      } else {
        router.navigate({ to: "/", search: { authenticated: "1" }, replace: true });
      }
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : t("login.defaultError"));
    } finally {
      setSubmitting(false);
    }
  };

  if (bootstrapStatus === "loading") {
    return (
      <div className="bg-muted/60 flex min-h-screen items-center justify-center px-4 py-12">
        <p className="text-muted-foreground text-sm">{t("common:loading")}</p>
      </div>
    );
  }

  if (bootstrapStatus === "required") {
    return <RegisterPage bootstrapMode />;
  }

  const isDark = document.documentElement.classList.contains("dark");

  return (
    <div
      style={{
        backgroundImage: `url(${isDark ? "/images/gridWhite.svg" : "/images/gridBlack.svg"})`,
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
            <CardTitle>{t("login.title")}</CardTitle>
            <CardDescription>{t("login.subtitle")}</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleSubmit} autoComplete="on">
              <div className="space-y-2">
                <Label htmlFor="email">{t("login.emailLabel")}</Label>
                <Input
                  id="email"
                  name="email"
                  type="email"
                  placeholder={t("login.emailPlaceholder")}
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="username"
                  autoCapitalize="none"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">{t("login.passwordLabel")}</Label>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  placeholder={t("login.passwordPlaceholder")}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                  required
                />
                <div className="text-right">
                  <Link
                    className="text-primary text-sm underline-offset-4 hover:underline"
                    to="/forgot-password"
                  >
                    {t("login.forgotPassword")}
                  </Link>
                </div>
              </div>
              <Button className="w-full" type="submit" disabled={submitting}>
                {submitting ? t("login.submitting") : t("login.submit")}
              </Button>
              {oidcLoginUrl ? (
                <Button
                  type="button"
                  variant="outline"
                  className="w-full"
                  onClick={async () => {
                    if (isNativePlatform && serverUrl) {
                      // On mobile, open in system browser with mobile flag and device name
                      const baseUrl = serverUrl.replace(/\/api\/v1\/?(\?.*)?$/, "");
                      let deviceName = "Mobile Device";
                      try {
                        const info = await Device.getInfo();
                        deviceName = info.name || info.model || "Mobile Device";
                      } catch {
                        // Fall back to default device name
                      }
                      const mobileLoginUrl = `${baseUrl}${oidcLoginUrl}?mobile=true&device_name=${encodeURIComponent(deviceName)}`;
                      await Browser.open({ url: mobileLoginUrl });
                    } else {
                      // On web, redirect directly
                      window.location.href = oidcLoginUrl;
                    }
                  }}
                >
                  {t("login.continueWith", {
                    provider: oidcProviderName ?? t("login.defaultSsoProvider"),
                  })}
                </Button>
              ) : null}
              {error ? <p className="text-destructive text-sm">{error}</p> : null}
            </form>
          </CardContent>
          <CardFooter className="text-muted-foreground flex flex-col items-start gap-2 text-sm">
            {isNativePlatform && (
              <p className="text-xs">
                {t("login.connectedTo")} <span className="font-medium">{getServerHostname()}</span>
                {" · "}
                <button
                  type="button"
                  className="text-primary underline-offset-4 hover:underline"
                  onClick={handleChangeServer}
                >
                  {t("login.changeServer")}
                </button>
              </p>
            )}
            <p>
              {t("login.needAccount")}{" "}
              <Link
                className="text-primary underline-offset-4 hover:underline"
                to="/register"
                search={inviteCodeParam ? { invite_code: inviteCodeParam } : undefined}
              >
                {t("login.register")}
              </Link>
            </p>
          </CardFooter>
        </Card>
      </div>
    </div>
  );
};
