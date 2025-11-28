import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

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
import { LogoIcon } from "@/components/LogoIcon";
import { RegisterPage } from "./RegisterPage";
import gridWhite from "@/assets/gridWhite.svg";
import gridBlack from "@/assets/gridBlack.svg";

export const LoginPage = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { login } = useAuth();
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
    const code = searchParams.get("invite_code");
    return code && code.trim().length > 0 ? code.trim() : null;
  }, [searchParams]);

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
          setOidcProviderName(response.data.provider_name ?? "Single Sign-On");
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
  }, []);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login({ email, password });
      if (inviteCodeParam) {
        navigate(`/invite/${encodeURIComponent(inviteCodeParam)}`, { replace: true });
      } else {
        navigate("/", { replace: true });
      }
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Unable to log in. Check your credentials.");
    } finally {
      setSubmitting(false);
    }
  };

  if (bootstrapStatus === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/60 px-4 py-12">
        <p className="text-sm text-muted-foreground">Loading…</p>
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
        backgroundImage: `url(${isDark ? gridWhite : gridBlack})`,
        backgroundPosition: "center",
        backgroundBlendMode: "screen",
        backgroundSize: "72px 72px",
      }}
    >
      <div className="flex flex-col gap-3 min-h-screen items-center justify-center bg-muted/60 px-4 py-12">
        <div className="flex items-center gap-3 text-3xl font-semibold tracking-tight text-primary">
          <LogoIcon className="h-12 w-12" aria-hidden="true" focusable="false" />
          initiative
        </div>
        <Card className="w-full max-w-md shadow-lg">
          <CardHeader>
            <CardTitle>Welcome back</CardTitle>
            <CardDescription>Sign in to keep work flowing.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleSubmit} autoComplete="on">
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  name="email"
                  type="email"
                  placeholder="you@company.com"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="username"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                  required
                />
                <div className="text-right">
                  <Link
                    className="text-sm text-primary underline-offset-4 hover:underline"
                    to="/forgot-password"
                  >
                    Forgot password?
                  </Link>
                </div>
              </div>
              <Button className="w-full" type="submit" disabled={submitting}>
                {submitting ? "Signing in…" : "Sign in"}
              </Button>
              {oidcLoginUrl ? (
                <Button
                  type="button"
                  variant="outline"
                  className="w-full"
                  onClick={() => (window.location.href = oidcLoginUrl)}
                >
                  Continue with {oidcProviderName ?? "Single Sign-On"}
                </Button>
              ) : null}
              {error ? <p className="text-sm text-destructive">{error}</p> : null}
            </form>
          </CardContent>
          <CardFooter className="flex flex-col items-start gap-2 text-sm text-muted-foreground">
            <p>
              Need an account?{" "}
              <Link
                className="text-primary underline-offset-4 hover:underline"
                to={
                  inviteCodeParam
                    ? `/register?invite_code=${encodeURIComponent(inviteCodeParam)}`
                    : "/register"
                }
              >
                Register
              </Link>
            </p>
          </CardFooter>
        </Card>
      </div>
    </div>
  );
};
