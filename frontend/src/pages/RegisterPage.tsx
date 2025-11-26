import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

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

interface RegisterPageProps {
  bootstrapMode?: boolean;
}

export const RegisterPage = ({ bootstrapMode = false }: RegisterPageProps) => {
  const navigate = useNavigate();
  const { register, login } = useAuth();
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setInfoMessage(null);
    try {
      const createdUser = await register({ email, password, full_name: fullName });
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
      setError("Unable to register. Try a different email.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/60 px-4 py-12">
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
            <Button className="w-full" type="submit" disabled={submitting}>
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
