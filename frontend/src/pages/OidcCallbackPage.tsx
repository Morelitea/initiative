import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { useAuth } from "../hooks/useAuth";

export const OidcCallbackPage = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { completeOidcLogin } = useAuth();
  const [status, setStatus] = useState("Finishing login…");

  useEffect(() => {
    const token = searchParams.get("token");
    const error = searchParams.get("error");
    if (error) {
      setStatus(`OIDC login failed: ${error}`);
      return;
    }
    if (!token) {
      setStatus("OIDC login failed: missing token");
      return;
    }
    const run = async () => {
      try {
        await completeOidcLogin(token);
        navigate("/", { replace: true });
      } catch (err) {
        console.error(err);
        setStatus("Unable to complete OIDC login.");
      }
    };
    void run();
  }, [completeOidcLogin, navigate, searchParams]);

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <Card className="w-full max-w-md shadow-sm">
        <CardHeader>
          <CardTitle>Signing you in…</CardTitle>
          <CardDescription>Hold tight while we finish authenticating your account.</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">{status}</p>
        </CardContent>
      </Card>
    </div>
  );
};
