import { useEffect, useState, useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import type { AxiosError } from "axios";

import { apiClient } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";
import type { GuildInviteStatus } from "@/types/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2 } from "lucide-react";
import { LogoIcon } from "@/components/LogoIcon";
import gridWhite from "@/assets/gridWhite.svg";
import gridBlack from "@/assets/gridBlack.svg";

export const GuildInvitePage = () => {
  const { code = "" } = useParams<{ code: string }>();
  const normalizedCode = code.trim();
  const registerLink = useMemo(
    () => `/register${normalizedCode ? `?invite_code=${encodeURIComponent(normalizedCode)}` : ""}`,
    [normalizedCode]
  );
  const { user, refreshUser } = useAuth();
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
      setError("Invite code is missing");
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
          setError(response.data.reason ?? "Invite is no longer valid.");
        }
      })
      .catch(() => {
        if (ignore) {
          return;
        }
        setError("Unable to load invite details. Please try again later.");
      })
      .finally(() => {
        if (!ignore) {
          setLoading(false);
        }
      });
    return () => {
      ignore = true;
    };
  }, [normalizedCode]);

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
      const axiosError = err as AxiosError<{ detail?: string }>;
      const detail = axiosError.response?.data?.detail;
      setAcceptError(detail ?? "Unable to accept invite right now.");
    } finally {
      setAccepting(false);
    }
  };

  const inviteValid = Boolean(status?.is_valid);
  const inviteTitle = inviteValid ? `Join ${status?.guild_name ?? "this guild"}` : "Guild invite";

  const isDark = document.documentElement.classList.contains("dark");

  return (
    <div
      style={{
        backgroundImage: `url(${isDark ? gridWhite : gridBlack})`,
        backgroundPosition: "center",
        backgroundBlendMode: "screen",
      }}
    >
      <div className="flex flex-col gap-3 min-h-screen items-center justify-center bg-muted/60 px-4 py-12">
        <div className="flex items-center gap-3 text-3xl font-semibold tracking-tight text-primary">
          <LogoIcon className="h-12 w-12" aria-hidden="true" focusable="false" />
          initiative
        </div>
        <Card className="w-full max-w-lg shadow-lg">
          <CardHeader>
            <CardTitle>{inviteTitle}</CardTitle>
            <CardDescription>
              {loading
                ? "Checking invite details…"
                : inviteValid
                  ? "Accept to join this guild."
                  : (error ?? "This invite could not be validated.")}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {loading ? (
              <p className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading invite…
              </p>
            ) : (
              <>
                <div className="rounded border bg-muted/40 p-4 text-sm">
                  <p>
                    <span className="font-medium">Invite code:</span> {normalizedCode || "—"}
                  </p>
                  <p>
                    <span className="font-medium">Guild:</span> {status?.guild_name ?? "Unknown"}
                  </p>
                  {status?.expires_at ? (
                    <p>
                      <span className="font-medium">Expires:</span>{" "}
                      {new Date(status.expires_at).toLocaleString()}
                    </p>
                  ) : null}
                  {status?.max_uses ? (
                    <p>
                      <span className="font-medium">Uses:</span> {status.uses ?? 0} /{" "}
                      {status.max_uses}
                    </p>
                  ) : null}
                </div>
                {inviteValid ? (
                  <div className="space-y-2 text-sm text-muted-foreground">
                    <p>If you already have an account, sign in and accept the invite.</p>
                    <p>
                      Need an account?{" "}
                      <Link
                        className="text-primary underline-offset-4 hover:underline"
                        to={registerLink}
                      >
                        Register using this invite
                      </Link>
                      .
                    </p>
                  </div>
                ) : null}
                {acceptError ? <p className="text-sm text-destructive">{acceptError}</p> : null}
                {accepted ? (
                  <p className="text-sm text-primary">
                    Invite accepted! You now have access to this guild.{" "}
                    <Link className="underline-offset-4 hover:underline" to="/">
                      Continue to dashboard
                    </Link>
                  </p>
                ) : null}
                <div className="flex flex-col gap-2">
                  <Button
                    onClick={handleAccept}
                    disabled={!user || !inviteValid || accepting || accepted}
                    className="w-full"
                  >
                    {accepting ? "Accepting…" : "Accept invite"}
                  </Button>
                  {!user ? (
                    <Link
                      className="text-sm text-center text-primary underline-offset-4 hover:underline"
                      to={`/login${normalizedCode ? `?invite_code=${encodeURIComponent(normalizedCode)}` : ""}`}
                    >
                      Sign in to accept
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
