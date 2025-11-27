import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
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
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { register, login } = useAuth();
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [inviteStatus, setInviteStatus] = useState<GuildInviteStatus | null>(null);
  const [inviteStatusError, setInviteStatusError] = useState<string | null>(null);
  const [inviteStatusLoading, setInviteStatusLoading] = useState(false);
  const inviteCode = useMemo(() => {
    const code = searchParams.get("invite_code");
    return code && code.trim().length > 0 ? code.trim() : undefined;
  }, [searchParams]);

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
      if (inviteCode && inviteStatus && !inviteStatus.is_valid) {
        setError(inviteStatus.reason ?? "Invite code is no longer valid.");
        return;
      }
      const createdUser = await register({ email, password, full_name: fullName, inviteCode });
      if (createdUser.is_active && createdUser.email_verified) {
        await login({ email, password });
        navigate("/", { replace: true });
      } else if (createdUser.is_active && !createdUser.email_verified) {
        setInfoMessage("Thanks! Check your inbox to verify your email before signing in.");
        setPassword("");
      } else {
        setInfoMessage("Thanks! Your account is pending approval from an administrator.");
        setPassword("");
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

  return (
    <div className="flex flex-col gap-3 min-h-screen items-center justify-center bg-muted/60 px-4 py-12">
      <div className="flex items-center gap-3 text-3xl font-semibold tracking-tight text-primary">
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
            {inviteCode ? (
              <p className="text-sm text-muted-foreground">
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
            {error ? <p className="text-sm text-destructive">{error}</p> : null}
            {infoMessage ? <p className="text-sm text-primary">{infoMessage}</p> : null}
          </form>
        </CardContent>
        <CardFooter className="text-sm text-muted-foreground">
          Have an account?{" "}
          <Link className="ml-1 text-primary underline-offset-4 hover:underline" to="/login">
            Sign in
          </Link>
        </CardFooter>
      </Card>
    </div>
  );
};
