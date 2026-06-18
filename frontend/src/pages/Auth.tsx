// src/pages/Auth.tsx
import React, { useState } from 'react';
import { api, setAccessToken, setRefreshToken } from '../api';
import { Shield, Mail, Phone, Lock, User as UserIcon, CheckCircle } from 'lucide-react';

interface AuthProps {
  onLoginSuccess: () => void;
}

export const Auth: React.FC<AuthProps> = ({ onLoginSuccess }) => {
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [otp, setOtp] = useState('');
  const [userIdForOtp, setUserIdForOtp] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setMessage('');
    setLoading(true);

    try {
      if (isLogin) {
        // Login flow
        const payload = email.includes('@') ? { email, password } : { phone: email, password };
        const data = await api.auth.login(payload);
        setAccessToken(data.access_token);
        setRefreshToken(data.refresh_token);
        onLoginSuccess();
      } else {
        // Registration flow
        const payload = {
          email: email || undefined,
          phone: phone || undefined,
          password,
          display_name: displayName,
        };
        const data = await api.auth.register(payload);
        setMessage(data.message);
        if (data.user_id && phone) {
          // Trigger OTP entry
          setUserIdForOtp(data.user_id);
        } else {
          // If no phone, direct login or auto-verify (e.g. email)
          setIsLogin(true);
          setEmail(email);
        }
      }
    } catch (err: any) {
      setError(err.message || 'An error occurred. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      if (!userIdForOtp) return;
      await api.auth.verifyOtp({
        user_id: userIdForOtp,
        otp,
        purpose: 'phone_verification',
      });
      setMessage('Phone verified! Please log in now.');
      setUserIdForOtp(null);
      setIsLogin(true);
    } catch (err: any) {
      setError(err.message || 'OTP verification failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '100vh',
      padding: '1.5rem',
      position: 'relative'
    }}>
      <div className="glass-card" style={{ maxWidth: '440px', width: '100%', padding: '2.5rem 2.25rem' }}>
        <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
          <div style={{
            display: 'inline-flex',
            padding: '1rem',
            background: 'var(--accent-indigo-glow)',
            border: '1px solid rgba(99, 102, 241, 0.2)',
            borderRadius: '16px',
            color: 'var(--accent-indigo)',
            marginBottom: '1rem'
          }}>
            <Shield size={32} />
          </div>
          <h2 style={{ fontSize: '1.85rem', marginBottom: '0.5rem' }}>AutoFormFiller</h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
            {userIdForOtp 
              ? 'Enter the 6-digit code printed in the console.' 
              : isLogin 
                ? 'Sign in to access your secure document vault.' 
                : 'Create an account to store docs and autofill forms.'
            }
          </p>
        </div>

        {error && (
          <div style={{
            background: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.2)',
            color: 'var(--color-danger)',
            padding: '0.85rem 1rem',
            borderRadius: '12px',
            fontSize: '0.85rem',
            marginBottom: '1.5rem'
          }}>
            {error}
          </div>
        )}

        {message && (
          <div style={{
            background: 'rgba(16, 185, 129, 0.1)',
            border: '1px solid rgba(16, 185, 129, 0.2)',
            color: 'var(--color-success)',
            padding: '0.85rem 1rem',
            borderRadius: '12px',
            fontSize: '0.85rem',
            marginBottom: '1.5rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem'
          }}>
            <CheckCircle size={16} />
            <span>{message}</span>
          </div>
        )}

        {userIdForOtp ? (
          <form onSubmit={handleVerifyOtp} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            <div className="form-group">
              <label htmlFor="otp">Enter Verification Code</label>
              <input
                id="otp"
                className="input-field"
                type="text"
                placeholder="000000"
                value={otp}
                onChange={(e) => setOtp(e.target.value)}
                maxLength={6}
                required
                style={{ textAlign: 'center', fontSize: '1.5rem', letterSpacing: '0.5rem' }}
              />
            </div>
            <button className="btn btn-primary" type="submit" disabled={loading} style={{ width: '100%' }}>
              {loading ? 'Verifying...' : 'Verify & Continue'}
            </button>
          </form>
        ) : (
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            {!isLogin && (
              <div className="form-group">
                <label htmlFor="name">Display Name</label>
                <div style={{ position: 'relative' }}>
                  <UserIcon size={18} style={{ position: 'absolute', left: '12px', top: '14px', color: 'var(--text-dim)' }} />
                  <input
                    id="name"
                    className="input-field"
                    type="text"
                    placeholder="Enter your name"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    required
                    style={{ paddingLeft: '2.5rem', width: '100%' }}
                  />
                </div>
              </div>
            )}

            <div className="form-group">
              <label htmlFor="email">{isLogin ? 'Email or Phone Number' : 'Email Address'}</label>
              <div style={{ position: 'relative' }}>
                <Mail size={18} style={{ position: 'absolute', left: '12px', top: '14px', color: 'var(--text-dim)' }} />
                <input
                  id="email"
                  className="input-field"
                  type="text"
                  placeholder={isLogin ? "email@example.com or +91..." : "email@example.com"}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required={isLogin || !phone}
                  style={{ paddingLeft: '2.5rem', width: '100%' }}
                />
              </div>
            </div>

            {!isLogin && (
              <div className="form-group">
                <label htmlFor="phone">Phone Number (Optional - for MFA/OTP)</label>
                <div style={{ position: 'relative' }}>
                  <Phone size={18} style={{ position: 'absolute', left: '12px', top: '14px', color: 'var(--text-dim)' }} />
                  <input
                    id="phone"
                    className="input-field"
                    type="tel"
                    placeholder="+919876543210"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    style={{ paddingLeft: '2.5rem', width: '100%' }}
                  />
                </div>
              </div>
            )}

            <div className="form-group">
              <label htmlFor="password">Password</label>
              <div style={{ position: 'relative' }}>
                <Lock size={18} style={{ position: 'absolute', left: '12px', top: '14px', color: 'var(--text-dim)' }} />
                <input
                  id="password"
                  className="input-field"
                  type="password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  style={{ paddingLeft: '2.5rem', width: '100%' }}
                />
              </div>
            </div>

            <button className="btn btn-primary" type="submit" disabled={loading} style={{ width: '100%', marginTop: '0.5rem' }}>
              {loading ? 'Please wait...' : isLogin ? 'Sign In' : 'Create Account'}
            </button>

            <div style={{ textAlign: 'center', marginTop: '1rem', fontSize: '0.875rem' }}>
              <span style={{ color: 'var(--text-muted)' }}>
                {isLogin ? "Don't have an account? " : "Already have an account? "}
              </span>
              <span
                onClick={() => {
                  setIsLogin(!isLogin);
                  setError('');
                  setMessage('');
                }}
                style={{ color: 'var(--accent-indigo)', fontWeight: '600', cursor: 'pointer', textDecoration: 'underline' }}
              >
                {isLogin ? 'Register' : 'Login'}
              </span>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};
