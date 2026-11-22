import React, { useState } from 'react';
import { AlertCircle, KeyRound, Loader2, Shield } from 'lucide-react';
import { ApiError, loginWithAccessToken } from '../api';

interface AccessLockViewProps {
  onAuthenticated: () => void;
}

export function AccessLockView({ onAuthenticated }: AccessLockViewProps) {
  const [token, setToken] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await loginWithAccessToken(token.trim());
      setToken('');
      onAuthenticated();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError('Не удалось связаться с сервером NEXUS Media');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="lock-screen">
      <section className="surface-card lock-card" aria-label="Авторизация доступа">
        <div className="brand-identity" style={{ marginBottom: '20px' }}>
          <div className="brand-mark" aria-hidden="true">
            N
            <span className="brand-tally" />
          </div>
          <div>
            <div className="brand-title">NEXUS Media</div>
            <div className="brand-subtitle">Личный узел обработки медиа</div>
          </div>
        </div>

        <h1 className="card-title" style={{ marginBottom: '8px' }}>
          Вход по коду доступа
        </h1>
        <p className="card-subtitle" style={{ marginBottom: '20px' }}>
          Сервер защищён приватным кодом доступа. Сессия сохранится в
          защищённом cookie на этом устройстве.
        </p>

        <form onSubmit={handleSubmit} className="lock-form">
          <div className="url-input-wrapper">
            <span className="url-input-icon" aria-hidden="true">
              <KeyRound size={18} strokeWidth={1.5} />
            </span>
            <input
              type="password"
              className="input-url input-token"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Введите код доступа"
              aria-label="Код доступа к NEXUS Media"
              autoComplete="current-password"
              autoFocus
              required
            />
          </div>

          {error && (
            <div className="alert-box alert-error" role="alert">
              <span className="icon-box" style={{ color: 'var(--danger)' }}>
                <AlertCircle size={18} strokeWidth={1.5} />
              </span>
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            className="btn btn-primary btn-lg"
            style={{ width: '100%' }}
            disabled={submitting || !token.trim()}
          >
            {submitting ? (
              <>
                <Loader2 size={18} strokeWidth={1.5} className="spin-icon" />
                <span>Проверка кода...</span>
              </>
            ) : (
              <>
                <Shield size={18} strokeWidth={1.5} />
                <span>Открыть доступ</span>
              </>
            )}
          </button>
        </form>
      </section>
    </div>
  );
}
