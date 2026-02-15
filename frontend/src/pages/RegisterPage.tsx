import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useRouter, useSearch } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { getErrorMessage } from "@/lib/errorMessage";
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
import type { GuildInviteStatus } from "@/types/api";
import { LogoIcon } from "@/components/LogoIcon";

interface RegisterPageProps {
  bootstrapMode?: boolean;
}

export const RegisterPage = ({ bootstrapMode = false }: RegisterPageProps) => {
  const { t } = useTranslation(["auth", "common"]);
  const router = useRouter();
  const searchParams = useSearch({ strict: false }) as { invite_code?: string };
  const { register, login } = useAuth();
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [inviteStatus, setInviteStatus] = useState<GuildInviteStatus | null>(null);
  const [inviteStatusError, setInviteStatusError] = useState<string | null>(null);
  const [inviteStatusLoading, setInviteStatusLoading] = useState(false);
  const [publicRegistrationEnabled, setPublicRegistrationEnabled] = useState<boolean | null>(null);
  const inviteCode = useMemo(() => {
    const code = searchParams.invite_code;
    return code && code.trim().length > 0 ? code.trim() : undefined;
  }, [searchParams]);

  // Fetch bootstrap status to check if public registration is enabled
  useEffect(() => {
    if (bootstrapMode) {
      // Bootstrap mode always allows registration
      setPublicRegistrationEnabled(true);
      return;
    }
    const fetchBootstrapStatus = async () => {
      try {
        const response = await apiClient.get<{
          has_users: boolean;
          public_registration_enabled: boolean;
        }>("/auth/bootstrap");
        setPublicRegistrationEnabled(response.data.public_registration_enabled);
      } catch {
        // Default to enabled if we can't fetch
        setPublicRegistrationEnabled(true);
      }
    };
    void fetchBootstrapStatus();
  }, [bootstrapMode]);

  useEffect(() => {
    let ignore = false;
    if (!inviteCode) {
      setInviteStatus(null);
      setInviteStatusError(null);
      setInviteStatusLoading(false);
      return () => {
        ignore = true;
      };
    }
    setInviteStatus(null);
    setInviteStatusError(null);
    setInviteStatusLoading(true);
    apiClient
      .get<GuildInviteStatus>(`/guilds/invite/${encodeURIComponent(inviteCode)}`)
      .then((response) => {
        if (ignore) {
          return;
        }
        setInviteStatus(response.data);
        setInviteStatusError(
          response.data.is_valid
            ? null
            : (response.data.reason ?? t("register.inviteNoLongerValid"))
        );
      })
      .catch((error) => {
        if (ignore) {
          return;
        }
        console.error("Failed to load invite", error);
        setInviteStatus(null);
        setInviteStatusError(t("register.unableToLoadInvite"));
      })
      .finally(() => {
        if (!ignore) {
          setInviteStatusLoading(false);
        }
      });
    return () => {
      ignore = true;
    };
  }, [inviteCode, t]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setInfoMessage(null);
    try {
      if (password !== confirmPassword) {
        setError(t("register.passwordMismatch"));
        return;
      }
      if (inviteCode && inviteStatus && !inviteStatus.is_valid) {
        setError(inviteStatus.reason ?? t("register.inviteInvalid"));
        return;
      }
      const createdUser = await register({
        email: email.toLowerCase().trim(),
        password,
        full_name: fullName,
        inviteCode,
      });
      if (createdUser.is_active && createdUser.email_verified) {
        await login({ email: email.toLowerCase().trim(), password });
        router.navigate({ to: "/", replace: true });
      } else if (createdUser.is_active && !createdUser.email_verified) {
        setInfoMessage(t("register.verifyEmailMessage"));
        setPassword("");
        setConfirmPassword("");
      } else {
        setInfoMessage(t("register.pendingApproval"));
        setPassword("");
        setConfirmPassword("");
      }
    } catch (err) {
      console.error(err);
      setError(getErrorMessage(err, "auth:register.defaultError"));
    } finally {
      setSubmitting(false);
    }
  };

  const isDark = document.documentElement.classList.contains("dark");

  // Show loading state while checking registration status
  if (publicRegistrationEnabled === null) {
    return (
      <div className="bg-muted/60 flex min-h-screen items-center justify-center px-4 py-12">
        <p className="text-muted-foreground text-sm">{t("common:loading")}</p>
      </div>
    );
  }

  // Show invite required message if public registration is disabled and no invite code
  if (!publicRegistrationEnabled && !inviteCode) {
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
              <CardTitle>{t("inviteRequired.title")}</CardTitle>
              <CardDescription>{t("inviteRequired.subtitle")}</CardDescription>
            </CardHeader>
            <CardFooter className="text-muted-foreground text-sm">
              {t("inviteRequired.haveAccount")}{" "}
              <Link className="text-primary ml-1 underline-offset-4 hover:underline" to="/login">
                {t("inviteRequired.signIn")}
              </Link>
            </CardFooter>
          </Card>
        </div>
      </div>
    );
  }

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
            <CardTitle>
              {bootstrapMode ? t("register.titleBootstrap") : t("register.title")}
            </CardTitle>
            <CardDescription>
              {bootstrapMode ? t("register.subtitleBootstrap") : t("register.subtitle")}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleSubmit}>
              <div className="space-y-2">
                <Label htmlFor="full-name">{t("register.fullNameLabel")}</Label>
                <Input
                  id="full-name"
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="register-email">{t("register.emailLabel")}</Label>
                <Input
                  id="register-email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoCapitalize="none"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="register-password">{t("register.passwordLabel")}</Label>
                <Input
                  id="register-password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirm-password">{t("register.confirmPasswordLabel")}</Label>
                <Input
                  id="confirm-password"
                  type="password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  required
                />
              </div>
              {inviteCode ? (
                <p className="text-muted-foreground text-sm">
                  {inviteStatusLoading && t("register.checkingInvite")}
                  {!inviteStatusLoading && inviteStatus && inviteStatus.is_valid
                    ? inviteStatus.guild_name
                      ? t("register.joiningGuild", { guildName: inviteStatus.guild_name })
                      : t("register.joiningGuildDefault")
                    : null}
                  {!inviteStatusLoading && inviteStatusError ? (
                    <span className="text-destructive">{inviteStatusError}</span>
                  ) : null}
                </p>
              ) : null}
              <Button
                className="w-full"
                type="submit"
                disabled={
                  submitting ||
                  (inviteCode
                    ? inviteStatusLoading || (inviteStatus ? !inviteStatus.is_valid : false)
                    : false)
                }
              >
                {submitting ? t("register.submitting") : t("register.submit")}
              </Button>
              {error ? <p className="text-destructive text-sm">{error}</p> : null}
              {infoMessage ? <p className="text-primary text-sm">{infoMessage}</p> : null}
            </form>
          </CardContent>
          <CardFooter className="text-muted-foreground text-sm">
            {t("register.haveAccount")}{" "}
            <Link className="text-primary ml-1 underline-offset-4 hover:underline" to="/login">
              {t("register.signIn")}
            </Link>
          </CardFooter>
        </Card>
      </div>
    </div>
  );
};
