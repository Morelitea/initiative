import { useEffect, useState } from "react";
import { Link, useSearch } from "@tanstack/react-router";

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

type VerificationStatus = "pending" | "success" | "error";

export const VerifyEmailPage = () => {
  const searchParams = useSearch({ strict: false }) as { token?: string };
  const token = searchParams.token;
  const [status, setStatus] = useState<VerificationStatus>("pending");
  const [message, setMessage] = useState("Verifying your email…");

  useEffect(() => {
    const verify = async () => {
      if (!token) {
        setStatus("error");
        setMessage("Verification link is missing.");
        return;
      }
      try {
        await apiClient.post("/auth/verification/confirm", { token });
        setStatus("success");
        setMessage("Email verified! You can sign in now.");
      } catch (err) {
        console.error(err);
        setStatus("error");
        setMessage("Verification link is invalid or expired.");
      }
    };
    void verify();
  }, [token]);

  return (
    <div className="bg-muted/60 flex min-h-screen items-center justify-center px-4 py-12">
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader>
          <CardTitle>Email verification</CardTitle>
          <CardDescription>{message}</CardDescription>
        </CardHeader>
        <CardContent>
          {status === "pending" ? (
            <p className="text-muted-foreground text-sm">Hang tight…</p>
          ) : null}
        </CardContent>
        <CardFooter className="text-muted-foreground flex flex-col gap-2 text-sm">
          {status === "success" ? (
            <Button asChild className="w-full">
              <Link to="/login">Go to sign in</Link>
            </Button>
          ) : (
            <Link className="text-primary underline-offset-4 hover:underline" to="/register">
              Need to register again?
            </Link>
          )}
        </CardFooter>
      </Card>
    </div>
  );
};
