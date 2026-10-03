import { Link, useParams } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import type { CommunityInviteStatus } from "@/api/generated/initiativeAPI.schemas";
import { ServerChip } from "@/components/auth/ServerChoice";
import { SignInFrame } from "@/components/auth/SignInFrame";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import { getErrorMessage } from "@/lib/errorMessage";
import { formatDateTime } from "@/lib/formatDate";

export const CommunityInvitePage = () => {
  const { code = "" } = useParams({ strict: false }) as { code: string };
  const normalizedCode = code.trim();
  const { user, refreshUser } = useAuth();
  const { refreshCommunities } = useCommunities();
  const { t } = useTranslation(["communities", "common"]);
  const [status, setStatus] = useState<CommunityInviteStatus | null>(null);
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
      .get<CommunityInviteStatus>(`/communities/invite/${encodeURIComponent(normalizedCode)}`)
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
      await apiClient.post("/communities/invite/accept", { code: normalizedCode });
      setAccepted(true);
      // Refresh both explicitly: joining changes the user's community list, and the
      // switcher only reloads when asked to. (It deliberately does not key off
      // the user object's identity — refreshUser() always returns a fresh one,
      // which would refetch every community on any profile change.)
      await Promise.all([refreshUser(), refreshCommunities()]);
    } catch (err) {
      setAcceptError(getErrorMessage(err, "communities:invite.unableToAccept"));
    } finally {
      setAccepting(false);
    }
  };

  const inviteValid = Boolean(status?.is_valid);
  const inviteTitle = inviteValid
    ? t("invite.title", { communityName: status?.community_name ?? "this community" })
    : t("invite.titleDefault");

  return (
    <SignInFrame>
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
            <p className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> {t("invite.loading")}
            </p>
          ) : (
            <>
              <div className="rounded border bg-muted/40 p-4 text-sm">
                <p>
                  <span className="font-medium">{t("invite.inviteCodeLabel")}</span>{" "}
                  {normalizedCode || "—"}
                </p>
                <p>
                  <span className="font-medium">{t("invite.communityLabel")}</span>{" "}
                  {status?.community_name ?? t("invite.unknown")}
                </p>
                {status?.expires_at ? (
                  <p>
                    <span className="font-medium">{t("invite.expiresLabel")}</span>{" "}
                    {formatDateTime(status.expires_at)}
                  </p>
                ) : null}
                {status?.max_uses ? (
                  <p>
                    <span className="font-medium">{t("invite.usesLabel")}</span> {status.uses ?? 0}{" "}
                    / {status.max_uses}
                  </p>
                ) : null}
              </div>
              {inviteValid ? (
                <div className="space-y-2 text-muted-foreground text-sm">
                  <p>{t("invite.alreadyHaveAccount")}</p>
                  <p>
                    {t("invite.needAccount")}{" "}
                    <Link
                      className="text-primary underline-offset-4 hover:underline"
                      to="/start"
                      search={normalizedCode ? { invite_code: normalizedCode } : {}}
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
                    className="text-center text-primary text-sm underline-offset-4 hover:underline"
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
        <CardFooter>
          <ServerChip />
        </CardFooter>
      </Card>
    </SignInFrame>
  );
};
