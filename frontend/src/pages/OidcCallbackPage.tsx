import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { useAuth } from '../hooks/useAuth';

export const OidcCallbackPage = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { completeOidcLogin } = useAuth();
  const [status, setStatus] = useState('Finishing login...');

  useEffect(() => {
    const token = searchParams.get('token');
    const error = searchParams.get('error');
    if (error) {
      setStatus(`OIDC login failed: ${error}`);
      return;
    }
    if (!token) {
      setStatus('OIDC login failed: missing token');
      return;
    }
    const run = async () => {
      try {
        await completeOidcLogin(token);
        navigate('/', { replace: true });
      } catch (err) {
        console.error(err);
        setStatus('Unable to complete OIDC login.');
      }
    };
    void run();
  }, [completeOidcLogin, navigate, searchParams]);

  return (
    <div className="page">
      <h1>Signing you in…</h1>
      <p>{status}</p>
    </div>
  );
};
