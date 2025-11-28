import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";

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
import { LogoIcon } from "@/components/LogoIcon";
import gridWhite from "@/assets/gridWhite.svg";
import gridBlack from "@/assets/gridBlack.svg";

export const ForgotPasswordPage = () => {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setStatus("sending");
    setError(null);
    try {
      await apiClient.post("/auth/password/forgot", { email });
      setStatus("sent");
    } catch (err) {
      console.error(err);
      setError("Unable to send reset email. Try again later.");
      setStatus("idle");
    }
  };

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
            <CardTitle>Reset password</CardTitle>
            <CardDescription>
              Enter the email tied to your account. We&apos;ll send a reset link if it exists.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleSubmit}>
              <div className="space-y-2">
                <Label htmlFor="forgot-email">Email</Label>
                <Input
                  id="forgot-email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  required
                  autoComplete="email"
                />
              </div>
              <Button className="w-full" type="submit" disabled={status === "sending"}>
                {status === "sending" ? "Sending…" : "Send reset link"}
              </Button>
              {error ? <p className="text-sm text-destructive">{error}</p> : null}
              {status === "sent" ? (
                <p className="text-sm text-primary">
                  If that account exists, a reset link is on its way to your inbox.
                </p>
              ) : null}
            </form>
          </CardContent>
          <CardFooter className="text-sm text-muted-foreground">
            Remembered it?{" "}
            <Link className="ml-1 text-primary underline-offset-4 hover:underline" to="/login">
              Go back to sign in
            </Link>
          </CardFooter>
        </Card>
      </div>
    </div>
  );
};
