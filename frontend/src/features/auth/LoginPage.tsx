import { useEffect, useRef, useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { errorMessage, isApiError } from '../../api/client';
import { Icon } from '../../components/Icon';
import { useAuth } from '../../app/AuthProvider';

interface LocationState {
  from?: string;
}

export function LoginPage() {
  const { status, login, bootError } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as LocationState | null)?.from ?? '/chat';

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<{ username?: string; password?: string }>({});
  const usernameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    usernameRef.current?.focus();
  }, []);

  if (status === 'authenticated') {
    return <Navigate to={from} replace />;
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const trimmed = username.trim();
    const nextFieldError: { username?: string; password?: string } = {};
    if (!trimmed) nextFieldError.username = '请输入账号';
    if (!password) nextFieldError.password = '请输入密码';
    setFieldError(nextFieldError);
    if (Object.keys(nextFieldError).length > 0) return;

    setBusy(true);
    setError(null);
    try {
      await login(trimmed, password);
      navigate(from, { replace: true });
    } catch (caught) {
      if (isApiError(caught) && caught.code === 'INVALID_CREDENTIALS') {
        setError('账号或密码不正确，请重新输入');
      } else if (isApiError(caught) && caught.code === 'ORIGIN_REJECTED') {
        setError('当前页面来源未被服务端信任，请从正式入口打开系统');
      } else if (isApiError(caught) && caught.code === 'CSRF_INVALID') {
        setError('登录校验失败，请刷新页面后重试');
      } else {
        setError(errorMessage(caught));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <main className="login-card">
        <div className="login-brand">
          <span className="login-brand-mark">
            <Icon name="book-open" size={22} />
          </span>
          <div>
            <p className="login-brand-name">市场部 AI 知识库</p>
            <p className="login-brand-sub">部门资料查询与问答</p>
          </div>
        </div>

        <h1 className="login-title">登录</h1>
        <p className="login-desc">使用管理员分配的账号登录。员工可查询已发布资料并查看来源，资料维护仅限管理员。</p>

        {bootError ? (
          <div className="notice notice-warning" role="status" style={{ marginTop: 16 }}>
            <Icon name="alert-circle" size={15} className="notice-icon" />
            <div className="notice-body">
              <p>{bootError}</p>
              <div className="notice-actions">
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => window.location.reload()}>
                  刷新页面
                </button>
              </div>
            </div>
          </div>
        ) : null}

        <form className="login-form" onSubmit={(event) => void handleSubmit(event)} noValidate>
          {error ? (
            <div className="form-error" role="alert">
              <Icon name="alert-circle" size={14} className="notice-icon" />
              <span>{error}</span>
            </div>
          ) : null}

          <div className="form-field">
            <label className="form-label" htmlFor="login-username">
              账号
            </label>
            <input
              id="login-username"
              ref={usernameRef}
              className="form-input"
              name="username"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              aria-invalid={Boolean(fieldError.username)}
              aria-describedby={fieldError.username ? 'login-username-error' : undefined}
              placeholder="请输入账号"
              disabled={busy}
            />
            {fieldError.username ? (
              <p className="form-error" id="login-username-error">
                {fieldError.username}
              </p>
            ) : null}
          </div>

          <div className="form-field">
            <label className="form-label" htmlFor="login-password">
              密码
            </label>
            <input
              id="login-password"
              className="form-input"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              aria-invalid={Boolean(fieldError.password)}
              aria-describedby={fieldError.password ? 'login-password-error' : undefined}
              placeholder="请输入密码"
              disabled={busy}
            />
            {fieldError.password ? (
              <p className="form-error" id="login-password-error">
                {fieldError.password}
              </p>
            ) : null}
          </div>

          <button type="submit" className="btn btn-primary btn-block" disabled={busy} style={{ height: 40 }}>
            {busy ? <span className="spinner spinner-sm" aria-hidden="true" /> : null}
            {busy ? '正在登录…' : '登录'}
          </button>
        </form>

        <p className="login-foot">
          未开放公共注册；账号与权限由服务端预置。登录会话保存在 HttpOnly Cookie 中，页面不保存密码或模型密钥。
        </p>
      </main>
    </div>
  );
}
