import { FormEvent, useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { apiClient } from '../api/client';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { useAuth } from '../hooks/useAuth';
import { RegisterPage } from './RegisterPage';

export const LoginPage = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [oidcLoginUrl, setOidcLoginUrl] = useState<string | null>(null);
  const [oidcProviderName, setOidcProviderName] = useState<string | null>(null);
  const forceBootstrap = searchParams.get('bootstrap') === '1';
  const [bootstrapStatus, setBootstrapStatus] = useState<'loading' | 'required' | 'ready'>(
    forceBootstrap ? 'required' : 'loading'
  );

  useEffect(() => {
    const fetchOidcStatus = async () => {
      try {
        const response = await apiClient.get<{ enabled: boolean; login_url?: string; provider_name?: string }>(
          '/auth/oidc/status'
        );
        if (response.data.enabled && response.data.login_url) {
          setOidcLoginUrl(response.data.login_url);
          setOidcProviderName(response.data.provider_name ?? 'Single Sign-On');
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
    if (forceBootstrap) {
      setBootstrapStatus('required');
      return;
    }

    let isMounted = true;
    let retryCount = 0;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const fetchBootstrapStatus = async () => {
      try {
        const response = await apiClient.get<{ has_users: boolean }>('/auth/bootstrap', {
          headers: { 'Cache-Control': 'no-store' },
        });
        if (!isMounted) {
          return;
        }
        setBootstrapStatus(response.data.has_users ? 'ready' : 'required');
      } catch (fetchError) {
        console.error('Failed to determine bootstrap status', fetchError);
        if (!isMounted) {
          return;
        }
        if (retryCount < 5) {
          const delay = Math.min(5000, 500 * 2 ** retryCount);
          retryCount += 1;
          retryTimer = setTimeout(fetchBootstrapStatus, delay);
        } else {
          setBootstrapStatus('required');
        }
      }
    };

    void fetchBootstrapStatus();

    return () => {
      isMounted = false;
      if (retryTimer) {
        clearTimeout(retryTimer);
      }
    };
  }, [forceBootstrap]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login({ email, password });
      navigate('/', { replace: true });
    } catch (err) {
      console.error(err);
      setError('Unable to log in. Check your credentials.');
    } finally {
      setSubmitting(false);
    }
  };

  if (bootstrapStatus === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/60 px-4 py-12">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    );
  }

  if (bootstrapStatus === 'required') {
    return <RegisterPage bootstrapMode />;
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/60 px-4 py-12">
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader>
          <CardTitle>Welcome back</CardTitle>
          <CardDescription>Sign in to keep work flowing.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="you@company.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </div>
            <Button className="w-full" type="submit" disabled={submitting}>
              {submitting ? 'Signing in…' : 'Sign in'}
            </Button>
            {oidcLoginUrl ? (
              <Button
                type="button"
                variant="outline"
                className="w-full"
                onClick={() => (window.location.href = oidcLoginUrl)}
              >
                Continue with {oidcProviderName ?? 'Single Sign-On'}
              </Button>
            ) : null}
            {error ? <p className="text-sm text-destructive">{error}</p> : null}
          </form>
        </CardContent>
        <CardFooter className="flex flex-col items-start gap-2 text-sm text-muted-foreground">
          <p>
            Need an account?{' '}
            <Link className="text-primary underline-offset-4 hover:underline" to="/register">
              Register
            </Link>
          </p>
        </CardFooter>
      </Card>
    </div>
  );
};
