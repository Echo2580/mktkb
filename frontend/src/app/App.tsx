import { Link, Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './AppShell';
import { RequireAuth } from './RequireAuth';
import { Icon } from '../components/Icon';
import { LoginPage } from '../features/auth/LoginPage';
import { ChatPage } from '../features/chat/ChatPage';
import { DocumentsPage } from '../features/documents/DocumentsPage';

function NotFoundPage() {
  return (
    <div className="page-scroll">
      <div className="page">
        <div className="empty-state" style={{ paddingTop: 60 }}>
          <span className="empty-icon">
            <Icon name="search-x" size={20} />
          </span>
          <h2 className="empty-title">页面不存在</h2>
          <p className="empty-desc">链接可能已失效，或该页面不属于当前版本。</p>
          <div className="state-actions">
            <Link className="btn btn-primary btn-md" to="/chat">
              返回 AI 助手
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route index element={<Navigate to="/chat" replace />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="chat/:conversationId" element={<ChatPage />} />
          <Route path="documents" element={<DocumentsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  );
}
