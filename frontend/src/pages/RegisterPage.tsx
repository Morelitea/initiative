import { FormEvent, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { useAuth } from '../hooks/useAuth';

export const RegisterPage = () => {
  const navigate = useNavigate();
  const { register, login } = useAuth();
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
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
      if (createdUser.is_active) {
        await login({ email, password });
        navigate('/', { replace: true });
      } else {
        setInfoMessage('Thanks! Your account is pending approval from an administrator.');
        setPassword('');
      }
    } catch (err) {
      console.error(err);
      setError('Unable to register. Try a different email.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="card" style={{ maxWidth: 420, margin: '4rem auto' }}>
        <h1>Create account</h1>
        <form onSubmit={handleSubmit}>
          <input
            type="text"
            placeholder="Full name"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
          />
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
          <button className="primary" type="submit" disabled={submitting}>
            {submitting ? 'Creating account...' : 'Sign up'}
          </button>
          {error ? <p style={{ color: 'tomato' }}>{error}</p> : null}
          {infoMessage ? <p style={{ color: '#2563eb' }}>{infoMessage}</p> : null}
        </form>
        <p>
          Have an account? <Link to="/login">Sign in</Link>
        </p>
      </div>
    </div>
  );
};
