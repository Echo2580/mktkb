import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from './AuthProvider';

export function FullPageLoading({ label = '正在加载…' }: { label?: string }) {
  return (
    <div style={{ display: 'flex', minHeight: '100dvh', alignItems: 'center', justifyContent: 'center', gap: 10, background: 'var(--slate-50)' }}>
      <span className="spinner" aria-hidden="true" />
      <span style={{ color: 'var(--slate-500)', fontSize: 13 }} role="status">
        {label}
      </span>
    </div>
  );
}

export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();

  if (status === 'loading') {
    return <FullPageLoading label="正在确认登录状态…" />;
  }

  if (status !== 'authenticated') {
    return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />;
  }

  return <Outlet />;
}
