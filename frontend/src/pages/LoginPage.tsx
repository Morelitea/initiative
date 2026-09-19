import { Browser } from "@capacitor/browser";
import { Device } from "@capacitor/device";
import { Link, useRouter, useSearch } from "@tanstack/react-router";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import type {
  LoginProviderEntry,
  LoginProvidersResponse,
} from "@/api/generated/initiativeAPI.schemas";
import { ProviderMark } from "@/components/auth/ProviderMark";
import { LogoIcon } from "@/components/LogoIcon";
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
import { useAppConfig } from "@/hooks/useAppConfig";
import { SecondFactorRequiredError, useAuth } from "@/hooks/useAuth";
import { useServer } from "@/hooks/useServer";
import { returnPath } from "@/lib/returnPath";

import { RegisterPage } from "./RegisterPage";

export const LoginPage = () => {
  const { t } = useTranslation(["auth", "common", "errors"]);
  const router = useRouter();
  const searchParams = useSearch({ strict: false }) as { invite_code?: string; next?: string };
  const { login, completeSecondFactor } = useAuth();
  const {
    isNativePlatform,
    isServerConfigured,
    getServerHostname,
    getServerOrigin,
    clearServerUrl,
    serverUrl,
  } = useServer();
  const { passwordLoginEnabled } = useAppConfig();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Set when the password was right and the account holds a second factor. The
  // card swaps to asking for the code; the challenge is held in memory only.
  const [challenge, setChallenge] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [useRecoveryCode, setUseRecoveryCode] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [providers, setProviders] = useState<LoginProviderEntry[]>([]);
  const [bootstrapStatus, setBootstrapStatus] = useState<"loading" | "required" | "ready">(
    "loading"
  );
  const inviteCodeParam = useMemo(() => {
    const code = searchParams.invite_code;
    return code && code.trim().length > 0 ? code.trim() : null;
  }, [searchParams]);

  // Fetch the sign-in providers the server offers (one button per provider).
  // Re-runs when the server becomes configured: on native the base URL is
  // hydrated after mount, and a fetch before that returns nothing.
  useEffect(() => {
    const fetchProviders = async () => {
      try {
        const response = await apiClient.get<LoginProvidersResponse>("/auth/providers");
        setProviders(response.data.providers);
      } catch {
        setProviders([]);
      }
    };
    void fetchProviders();
  }, [isServerConfigured]);

  const handleProviderLogin = async (provider: LoginProviderEntry) => {
    if (isNativePlatform && serverUrl) {
      // On mobile, open in system browser with mobile flag and device name
      const baseUrl = getServerOrigin() ?? serverUrl;
      let deviceName = "Mobile Device";
      try {
        const info = await Device.getInfo();
        deviceName = info.name || info.model || "Mobile Device";
      } catch {
        // Fall back to default device name
      }
      const mobileLoginUrl = `${baseUrl}${provider.login_url}?mobile=true&device_name=${encodeURIComponent(deviceName)}`;
      await Browser.open({ url: mobileLoginUrl });
    } else {
      // On web, redirect directly — carrying where they were headed, so an
      // account that only signs in through a provider finishes the trip it
      // started. The server reads `next` back on its callback.
      const next = returnPath(searchParams.next);
      window.location.href = next
        ? `${provider.login_url}?next=${encodeURIComponent(next)}`
        : provider.login_url;
    }
  };

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

  const goWhereTheySignedInFor = () => {
    // The page they were headed for before they were asked to sign in, if it
    // is a path in this app. An invite still wins: it is why they are here.
    const returnTo = returnPath(searchParams.next) ?? "/";
    if (inviteCodeParam) {
      router.navigate({
        to: "/invite/$code",
        params: { code: encodeURIComponent(inviteCodeParam) },
        replace: true,
      });
    } else {
      router.navigate({ to: returnTo, replace: true });
    }
  };

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
      goWhereTheySignedInFor();
    } catch (err) {
      if (err instanceof SecondFactorRequiredError) {
        // Not a failure — the sign-in is half done. Drop the password; it has
        // served its purpose and the code is what is asked for now.
        setChallenge(err.challenge);
        setPassword("");
        setError(null);
        return;
      }
      console.error(err);
      setError(err instanceof Error ? err.message : t("login.defaultError"));
    } finally {
      setSubmitting(false);
    }
  };

  const handleCodeSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!challenge) return;
    setSubmitting(true);
    setError(null);
    try {
      const entered = code.trim();
      await completeSecondFactor({
        challenge,
        ...(useRecoveryCode ? { recoveryCode: entered } : { code: entered }),
      });
      goWhereTheySignedInFor();
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : t("login.defaultError"));
      setCode("");
    } finally {
      setSubmitting(false);
    }
  };

  const startOver = () => {
    setChallenge(null);
    setCode("");
    setUseRecoveryCode(false);
    setError(null);
  };

  if (bootstrapStatus === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/60 px-4 py-12">
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
        backgroundImage: `url(${isDark ? "/images/hexWhite.svg" : "/images/hexBlack.svg"})`,
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
            <CardTitle>{challenge ? t("secondFactor.title") : t("login.title")}</CardTitle>
            <CardDescription>
              {challenge
                ? useRecoveryCode
                  ? t("secondFactor.recoverySubtitle")
                  : t("secondFactor.subtitle")
                : t("login.subtitle")}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {challenge ? (
              <form className="space-y-4" onSubmit={handleCodeSubmit}>
                <div className="space-y-2">
                  <Label htmlFor="second-factor-code">
                    {useRecoveryCode
                      ? t("secondFactor.recoveryLabel")
                      : t("secondFactor.codeLabel")}
                  </Label>
                  <Input
                    id="second-factor-code"
                    name="second-factor-code"
                    // A recovery code carries letters and dashes; a live code
                    // is six digits, and the numeric keypad is what a phone
                    // should offer for it.
                    inputMode={useRecoveryCode ? "text" : "numeric"}
                    autoComplete="one-time-code"
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    // The only field on a step the person was just sent to,
                    // mid-sign-in.
                    autoFocus
                    placeholder={
                      useRecoveryCode
                        ? t("secondFactor.recoveryPlaceholder")
                        : t("secondFactor.codePlaceholder")
                    }
                    value={code}
                    onChange={(event) => setCode(event.target.value)}
                    required
                  />
                </div>
                <Button className="w-full" type="submit" disabled={submitting || !code.trim()}>
                  {submitting ? t("login.submitting") : t("secondFactor.submit")}
                </Button>
                <div className="flex items-center justify-between text-sm">
                  <button
                    type="button"
                    className="text-primary underline-offset-4 hover:underline"
                    onClick={() => {
                      setUseRecoveryCode((previous) => !previous);
                      setCode("");
                      setError(null);
                    }}
                  >
                    {useRecoveryCode
                      ? t("secondFactor.useAuthenticator")
                      : t("secondFactor.useRecoveryCode")}
                  </button>
                  <button
                    type="button"
                    className="text-muted-foreground underline-offset-4 hover:underline"
                    onClick={startOver}
                  >
                    {t("secondFactor.startOver")}
                  </button>
                </div>
                {error ? <p className="text-destructive text-sm">{error}</p> : null}
              </form>
            ) : (
              <form className="space-y-4" onSubmit={handleSubmit} autoComplete="on">
                {/* Offered only where the deployment permits it. The server
                  refuses the sign-in either way; this keeps the page from
                  presenting a form that cannot work. */}
                {passwordLoginEnabled ? (
                  <>
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
                  </>
                ) : null}
                {providers.map((provider) => (
                  <Button
                    key={provider.slug}
                    type="button"
                    variant="outline"
                    className="w-full"
                    onClick={() => void handleProviderLogin(provider)}
                  >
                    <ProviderMark icon={provider.icon} className="h-4 w-4" />
                    {t("login.continueWith", { provider: provider.display_name })}
                  </Button>
                ))}
                {error ? <p className="text-destructive text-sm">{error}</p> : null}
              </form>
            )}
          </CardContent>
          <CardFooter className="flex flex-col items-start gap-2 text-muted-foreground text-sm">
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
            {passwordLoginEnabled ? (
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
            ) : null}
          </CardFooter>
        </Card>
      </div>
    </div>
  );
};
