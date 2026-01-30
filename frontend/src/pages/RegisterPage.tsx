import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useRouter, useSearch } from "@tanstack/react-router";
import type { AxiosError } from "axios";

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
import type { GuildInviteStatus } from "@/types/api";
import { LogoIcon } from "@/components/LogoIcon";

interface RegisterPageProps {
  bootstrapMode?: boolean;
}

export const RegisterPage = ({ bootstrapMode = false }: RegisterPageProps) => {
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
          response.data.is_valid ? null : (response.data.reason ?? "Invite is no longer valid.")
        );
      })
      .catch((error) => {
        if (ignore) {
          return;
        }
        console.error("Failed to load invite", error);
        setInviteStatus(null);
        setInviteStatusError("Unable to load invite details right now.");
      })
      .finally(() => {
        if (!ignore) {
          setInviteStatusLoading(false);
        }
      });
    return () => {
      ignore = true;
    };
  }, [inviteCode]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setInfoMessage(null);
    try {
      if (password !== confirmPassword) {
        setError("Passwords do not match.");
        return;
      }
      if (inviteCode && inviteStatus && !inviteStatus.is_valid) {
        setError(inviteStatus.reason ?? "Invite code is no longer valid.");
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
        setInfoMessage("Thanks! Check your inbox to verify your email before signing in.");
        setPassword("");
        setConfirmPassword("");
      } else {
        setInfoMessage("Thanks! Your account is pending approval from an administrator.");
        setPassword("");
        setConfirmPassword("");
      }
    } catch (err) {
      console.error(err);
      const axiosError = err as AxiosError<{ detail?: string }>;
      const detail = axiosError.response?.data?.detail;
      setError(detail ?? "Unable to register. Try a different email.");
    } finally {
      setSubmitting(false);
    }
  };

  const isDark = document.documentElement.classList.contains("dark");

  // Show loading state while checking registration status
  if (publicRegistrationEnabled === null) {
    return (
      <div className="bg-muted/60 flex min-h-screen items-center justify-center px-4 py-12">
        <p className="text-muted-foreground text-sm">Loading…</p>
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
            initiative
          </div>
          <Card className="w-full max-w-md shadow-lg">
            <CardHeader>
              <CardTitle>Invite required</CardTitle>
              <CardDescription>
                Public registration is not available. Please ask an existing member for an invite
                link to join.
              </CardDescription>
            </CardHeader>
            <CardFooter className="text-muted-foreground text-sm">
              Already have an account?{" "}
              <Link className="text-primary ml-1 underline-offset-4 hover:underline" to="/login">
                Sign in
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
          initiative
        </div>
        <Card className="w-full max-w-md shadow-lg">
          <CardHeader>
            <CardTitle>{bootstrapMode ? "Create the first account" : "Create account"}</CardTitle>
            <CardDescription>
              {bootstrapMode
                ? "No users exist yet. This account will become the workspace super user."
                : "We will auto-approve your email if it matches the workspace allow list."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleSubmit}>
              <div className="space-y-2">
                <Label htmlFor="full-name">Full name</Label>
                <Input
                  id="full-name"
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="register-email">Email</Label>
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
                <Label htmlFor="register-password">Password</Label>
                <Input
                  id="register-password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirm-password">Confirm password</Label>
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
                  {inviteStatusLoading && "Checking invite…"}
                  {!inviteStatusLoading && inviteStatus && inviteStatus.is_valid
                    ? `You’re joining ${inviteStatus.guild_name ?? "this guild"}.`
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
                {submitting ? "Creating account…" : "Sign up"}
              </Button>
              {error ? <p className="text-destructive text-sm">{error}</p> : null}
              {infoMessage ? <p className="text-primary text-sm">{infoMessage}</p> : null}
            </form>
          </CardContent>
          <CardFooter className="text-muted-foreground text-sm">
            Have an account?{" "}
            <Link className="text-primary ml-1 underline-offset-4 hover:underline" to="/login">
              Sign in
            </Link>
          </CardFooter>
        </Card>
      </div>
    </div>
  );
};
