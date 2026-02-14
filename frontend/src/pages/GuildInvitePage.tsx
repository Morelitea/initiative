import { useEffect, useState, useMemo } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { getErrorMessage } from "@/lib/errorMessage";
import { useAuth } from "@/hooks/useAuth";
import type { GuildInviteStatus } from "@/types/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2 } from "lucide-react";
import { LogoIcon } from "@/components/LogoIcon";

export const GuildInvitePage = () => {
  const { code = "" } = useParams({ strict: false }) as { code: string };
  const normalizedCode = code.trim();
  const registerLink = useMemo(
    () => `/register${normalizedCode ? `?invite_code=${encodeURIComponent(normalizedCode)}` : ""}`,
    [normalizedCode]
  );
  const { user, refreshUser } = useAuth();
  const { t } = useTranslation("guilds");
  const [status, setStatus] = useState<GuildInviteStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [accepting, setAccepting] = useState(false);
  const [acceptError, setAcceptError] = useState<string | null>(null);
  const [accepted, setAccepted] = useState(false);

  useEffect(() => {
    let ignore = false;
    if (!normalizedCode) {
      setStatus(null);
      setLoading(false);
      setError(t("invite.codeMissing"));
      return;
    }
    setLoading(true);
    setError(null);
    setStatus(null);
    apiClient
      .get<GuildInviteStatus>(`/guilds/invite/${encodeURIComponent(normalizedCode)}`)
      .then((response) => {
        if (ignore) {
          return;
        }
        setStatus(response.data);
        if (!response.data.is_valid) {
          setError(response.data.reason ?? t("invite.noLongerValid"));
        }
      })
      .catch(() => {
        if (ignore) {
          return;
        }
        setError(t("invite.unableToLoad"));
      })
      .finally(() => {
        if (!ignore) {
          setLoading(false);
        }
      });
    return () => {
      ignore = true;
    };
  }, [normalizedCode, t]);

  const handleAccept = async () => {
    if (!normalizedCode || !user) {
      return;
    }
    setAccepting(true);
    setAcceptError(null);
    try {
      await apiClient.post("/guilds/invite/accept", { code: normalizedCode });
      setAccepted(true);
      await refreshUser();
    } catch (err) {
      setAcceptError(getErrorMessage(err, "guilds:invite.unableToAccept"));
    } finally {
      setAccepting(false);
    }
  };

  const inviteValid = Boolean(status?.is_valid);
  const inviteTitle = inviteValid
    ? t("invite.title", { guildName: status?.guild_name ?? "this guild" })
    : t("invite.titleDefault");

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
        <Card className="w-full max-w-lg shadow-lg">
          <CardHeader>
            <CardTitle>{inviteTitle}</CardTitle>
            <CardDescription>
              {loading
                ? t("invite.checking")
                : inviteValid
                  ? t("invite.acceptDescription")
                  : (error ?? t("invite.couldNotValidate"))}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {loading ? (
              <p className="text-muted-foreground flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" /> {t("invite.loading")}
              </p>
            ) : (
              <>
                <div className="bg-muted/40 rounded border p-4 text-sm">
                  <p>
                    <span className="font-medium">{t("invite.inviteCodeLabel")}</span>{" "}
                    {normalizedCode || "—"}
                  </p>
                  <p>
                    <span className="font-medium">{t("invite.guildLabel")}</span>{" "}
                    {status?.guild_name ?? t("invite.unknown")}
                  </p>
                  {status?.expires_at ? (
                    <p>
                      <span className="font-medium">{t("invite.expiresLabel")}</span>{" "}
                      {new Date(status.expires_at).toLocaleString()}
                    </p>
                  ) : null}
                  {status?.max_uses ? (
                    <p>
                      <span className="font-medium">{t("invite.usesLabel")}</span>{" "}
                      {status.uses ?? 0} / {status.max_uses}
                    </p>
                  ) : null}
                </div>
                {inviteValid ? (
                  <div className="text-muted-foreground space-y-2 text-sm">
                    <p>{t("invite.alreadyHaveAccount")}</p>
                    <p>
                      {t("invite.needAccount")}{" "}
                      <Link
                        className="text-primary underline-offset-4 hover:underline"
                        to={registerLink}
                      >
                        {t("invite.registerWithInvite")}
                      </Link>
                      .
                    </p>
                  </div>
                ) : null}
                {acceptError ? <p className="text-destructive text-sm">{acceptError}</p> : null}
                {accepted ? <p className="text-primary text-sm">{t("invite.accepted")}</p> : null}
                <div className="flex flex-col gap-2">
                  {accepted ? (
                    <Button asChild className="w-full">
                      <Link to="/">{t("invite.continueToApp")}</Link>
                    </Button>
                  ) : (
                    <Button
                      onClick={handleAccept}
                      disabled={!user || !inviteValid || accepting || accepted}
                      className="w-full"
                    >
                      {accepting ? t("invite.accepting") : t("invite.acceptInvite")}
                    </Button>
                  )}

                  {!user ? (
                    <Link
                      className="text-primary text-center text-sm underline-offset-4 hover:underline"
                      to="/login"
                      search={normalizedCode ? { invite_code: normalizedCode } : undefined}
                    >
                      {t("invite.signInToAccept")}
                    </Link>
                  ) : null}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
};
