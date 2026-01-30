import { FormEvent, useState } from "react";
import { Link, useRouter, useSearch } from "@tanstack/react-router";

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

export const ResetPasswordPage = () => {
  const searchParams = useSearch({ strict: false }) as { token?: string };
  const router = useRouter();
  const token = searchParams.token ?? "";
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [status, setStatus] = useState<"idle" | "submitting" | "success">("idle");
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token) {
      setError("Reset link is missing. Use the email link again.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setStatus("submitting");
    setError(null);
    try {
      await apiClient.post("/auth/password/reset", { token, password });
      setStatus("success");
    } catch (err) {
      console.error(err);
      setError("Unable to reset password. The link may have expired.");
      setStatus("idle");
    }
  };

  if (!token) {
    return (
      <div className="bg-muted/60 flex min-h-screen items-center justify-center px-4 py-12">
        <Card className="w-full max-w-md shadow-lg">
          <CardHeader>
            <CardTitle>Reset password</CardTitle>
            <CardDescription>This link is invalid. Request a new one.</CardDescription>
          </CardHeader>
          <CardFooter className="text-muted-foreground text-sm">
            <Link className="text-primary underline-offset-4 hover:underline" to="/forgot-password">
              Request password reset
            </Link>
          </CardFooter>
        </Card>
      </div>
    );
  }

  return (
    <div className="bg-muted/60 flex min-h-screen items-center justify-center px-4 py-12">
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader>
          <CardTitle>Choose a new password</CardTitle>
          <CardDescription>Enter and confirm your new password to continue.</CardDescription>
        </CardHeader>
        <CardContent>
          {status === "success" ? (
            <div className="text-primary space-y-4 text-sm">
              <p>Password updated successfully.</p>
              <Button className="w-full" onClick={() => router.navigate({ to: "/login" })}>
                Go to sign in
              </Button>
            </div>
          ) : (
            <form className="space-y-4" onSubmit={handleSubmit}>
              <div className="space-y-2">
                <Label htmlFor="new-password">New password</Label>
                <Input
                  id="new-password"
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
              <Button className="w-full" type="submit" disabled={status === "submitting"}>
                {status === "submitting" ? "Updating…" : "Reset password"}
              </Button>
              {error ? <p className="text-destructive text-sm">{error}</p> : null}
            </form>
          )}
        </CardContent>
        {status !== "success" ? (
          <CardFooter className="text-muted-foreground text-sm">
            <Link className="text-primary underline-offset-4 hover:underline" to="/forgot-password">
              Need a new link?
            </Link>
          </CardFooter>
        ) : null}
      </Card>
    </div>
  );
};
