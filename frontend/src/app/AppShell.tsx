import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation, useMatch, useNavigate } from 'react-router-dom';
import { api, errorMessage } from '../api/client';
import type { ConversationSummary } from '../api/client';
import { Icon } from '../components/Icon';
import { ConfirmDialog } from '../components/Dialog';
import { useAuth } from './AuthProvider';
import { useToast } from './ToastProvider';
import { formatDay } from '../utils/format';

type ConversationLoadFailure = 'loadMore' | 'resync';

export interface ShellContextValue {
  conversations: ConversationSummary[];
  conversationsLoading: boolean;
  conversationsError: string | null;
  conversationsTotal: number;
  conversationsHasMore: boolean;
  conversationsLoadingMore: boolean;
  conversationsLoadMoreError: string | null;
  reloadConversations: () => Promise<void>;
  loadMoreConversations: () => Promise<void>;
}

interface SidebarContentProps {
  conversations: ConversationSummary[];
  loading: boolean;
  error: string | null;
  total: number;
  hasMore: boolean;
  loadingMore: boolean;
  loadMoreError: string | null;
  syncNotice: string | null;
  role: string;
  displayName: string;
  activeId: string | null;
  onNavigate?: () => void;
  onDelete: (conversation: ConversationSummary) => void;
  onLogout: () => void;
  onRetry: () => void;
  onLoadMore: () => void;
  onRetryLoadMore: () => void;
  onResync: () => void;
  hideBrand?: boolean;
}

function roleLabel(role: string): string {
  return role === 'admin' ? '管理员' : '员工';
}

function mergeConversations(
  current: ConversationSummary[],
  incoming: ConversationSummary[],
): { items: ConversationSummary[]; added: number } {
  const known = new Set(current.map((conversation) => conversation.id));
  const items = [...current];
  for (const conversation of incoming) {
    if (known.has(conversation.id)) continue;
    known.add(conversation.id);
    items.push(conversation);
  }
  return { items, added: items.length - current.length };
}

function recoveryNotice(loaded: number, total: number, serverChanged: boolean): string | null {
  if (loaded > total) {
    return `会话数量已变为 ${total}，当前列表含 ${loaded} 条。请重新同步列表以移除失效条目。`;
  }
  if (loaded < total) {
    return `会话列表在加载期间发生变化，仍有 ${total - loaded} 条未显示。可重新同步列表或继续加载。`;
  }
  // 数量相等不足以证明身份一致：服务端总数在本次加载期间变化时，
  // 旧窗口可能仍含已删除条目并漏掉现存条目，必须保留可重建列表的入口。
  if (serverChanged) {
    return `会话列表在加载期间发生变化（共 ${total} 条），当前列表可能含失效条目或漏项。请重新同步列表。`;
  }
  return null;
}

function SidebarContent({
  conversations,
  loading,
  error,
  total,
  hasMore,
  loadingMore,
  loadMoreError,
  syncNotice,
  role,
  displayName,
  activeId,
  onNavigate,
  onDelete,
  onLogout,
  onRetry,
  onLoadMore,
  onRetryLoadMore,
  onResync,
  hideBrand = false,
}: SidebarContentProps) {
  const isNewChat = activeId === null;
  return (
    <>
      {hideBrand ? null : (
        <div className="sidebar-brand">
          <NavLink to="/chat" className="brand-link" onClick={onNavigate}>
            <span className="brand-mark">
              <Icon name="book-open" size={19} />
            </span>
            <span className="brand-text">
              <span className="brand-name">市场部 AI 知识库</span>
              <span className="brand-sub">部门知识查询</span>
            </span>
          </NavLink>
        </div>
      )}

      <div className="nav-section">
        <p className="nav-caption">工作台</p>
        <nav aria-label="主要导航" className="nav-list">
          <NavLink to="/chat" className={({ isActive }) => `nav-item${isActive ? ' is-active' : ''}`} onClick={onNavigate}>
            <Icon name="sparkles" size={17} className="nav-icon" />
            <span>AI 助手</span>
          </NavLink>
          {role === 'admin' ? (
            <NavLink
              to="/documents"
              className={({ isActive }) => `nav-item${isActive ? ' is-active' : ''}`}
              onClick={onNavigate}
            >
              <Icon name="files" size={17} className="nav-icon" />
              <span>资料管理</span>
            </NavLink>
          ) : null}
        </nav>
      </div>

      <div className="new-chat-wrap">
        <NavLink
          to="/chat"
          className="new-chat-button"
          aria-current={isNewChat ? 'page' : undefined}
          onClick={onNavigate}
        >
          <span className="new-chat-label">
            <Icon name="plus" size={16} />
            <span>新建对话</span>
          </span>
          <span className="new-chat-tag">{isNewChat ? '当前' : '新建'}</span>
        </NavLink>
      </div>

      <div className="conversation-section">
        <div className="conversation-head">
          <h2 className="conversation-caption">最近对话</h2>
          <div className="conversation-head-actions">
            <span className="conversation-count">{total > 0 ? `${conversations.length}/${total}` : conversations.length}</span>
            {!loading && !error && !syncNotice && !loadMoreError ? (
              <button
                type="button"
                className="btn-link conversation-sync"
                onClick={onResync}
                disabled={loadingMore}
                title="重新读取最新会话列表"
              >
                同步会话列表
              </button>
            ) : null}
          </div>
        </div>
        <nav aria-label="最近对话" className="conversation-list">
          {loading ? <p className="conversation-caption" style={{ padding: '0 8px' }}>正在加载会话…</p> : null}
          {error && !loading ? (
            <div style={{ padding: '0 8px' }}>
              <p className="conversation-caption" style={{ color: 'var(--rose-700)' }}>{error}</p>
              <button type="button" className="btn-link" style={{ marginTop: 4 }} onClick={onRetry}>
                重试
              </button>
            </div>
          ) : null}
          {!loading && !error && conversations.length === 0 ? (
            <p className="conversation-caption" style={{ padding: '0 8px', lineHeight: '18px' }}>
              还没有对话。发送第一个问题后会出现在这里。
            </p>
          ) : null}
          {conversations.map((conversation) => (
            <div key={conversation.id} className={`conversation-item${conversation.id === activeId ? ' is-active' : ''}`}>
              <Icon name="message-square" size={14} className="conversation-icon" />
              <NavLink
                to={`/chat/${conversation.id}`}
                className="conversation-title"
                aria-current={conversation.id === activeId ? 'page' : undefined}
                onClick={onNavigate}
              >
                {conversation.title}
              </NavLink>
              <button
                type="button"
                className="conversation-delete"
                aria-label={`删除会话：${conversation.title}`}
                title="删除会话"
                onClick={() => onDelete(conversation)}
              >
                <Icon name="trash-2" size={13} />
              </button>
            </div>
          ))}
          {syncNotice ? (
            <div style={{ padding: '6px 8px 8px' }}>
              <p className="conversation-caption" style={{ lineHeight: '17px' }} role="status">
                {syncNotice}
              </p>
              <button type="button" className="btn-link" style={{ marginTop: 4 }} onClick={onResync} disabled={loadingMore}>
                {loadingMore ? '正在同步会话列表…' : '重新同步列表'}
              </button>
            </div>
          ) : null}
          {loadMoreError ? (
            <div style={{ padding: '6px 8px 8px' }}>
              <p className="conversation-caption" style={{ color: 'var(--rose-700)' }} role="alert">
                {loadMoreError}
              </p>
              <button type="button" className="btn-link" style={{ marginTop: 4 }} onClick={onRetryLoadMore}>
                重试加载
              </button>
            </div>
          ) : null}
          {hasMore ? (
            <div style={{ padding: '6px 8px 8px' }}>
              <button
                type="button"
                className="btn-link"
                onClick={onLoadMore}
                disabled={loadingMore || Boolean(loadMoreError)}
              >
                {loadingMore
                  ? '正在加载更早会话…'
                  : `加载更早会话（已显示 ${conversations.length} / 共 ${total}）`}
              </button>
            </div>
          ) : !syncNotice && !loading && !error && total > 0 ? (
            <p className="conversation-caption" style={{ padding: '6px 8px 8px' }}>
              共 {total} 条，已全部显示
            </p>
          ) : null}
        </nav>
      </div>

      <div className="sidebar-user">
        <div className="user-row">
          <div className="avatar" aria-hidden="true">
            {displayName.slice(0, 1) || '用'}
          </div>
          <div className="user-meta">
            <p className="user-name truncate">{displayName}</p>
            <p className="user-role truncate">市场部 · {roleLabel(role)}</p>
          </div>
          <button type="button" className="icon-button" aria-label="退出登录" title="退出登录" onClick={onLogout}>
            <Icon name="log-out" size={16} />
          </button>
        </div>
      </div>
    </>
  );
}

export function AppShell() {
  const { user, logout } = useAuth();
  const { push } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const match = useMatch('/chat/:conversationId');
  const activeId = match?.params.conversationId ?? null;
  const isDocuments = location.pathname.startsWith('/documents');

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [loadMoreErrorAction, setLoadMoreErrorAction] = useState<ConversationLoadFailure | null>(null);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [logoutOpen, setLogoutOpen] = useState(false);
  const [logoutBusy, setLogoutBusy] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ConversationSummary | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const conversationSeq = useRef(0);
  const loadingMoreRef = useRef(false);
  const nextOffsetRef = useRef(0);

  const reloadConversations = useCallback(async () => {
    const seq = ++conversationSeq.current;
    setLoading(true);
    try {
      const data = await api.listConversations(0, 50);
      if (seq !== conversationSeq.current) return;
      const page = mergeConversations([], data.items);
      setConversations(page.items);
      setTotal(data.total);
      nextOffsetRef.current = data.items.length;
      setError(null);
      setLoadMoreError(null);
      setLoadMoreErrorAction(null);
      setSyncNotice(null);
    } catch (caught) {
      if (seq !== conversationSeq.current) return;
      setError(errorMessage(caught));
    } finally {
      if (seq === conversationSeq.current) setLoading(false);
    }
  }, []);

  const loadMoreConversations = useCallback(async () => {
    if (loading || loadingMoreRef.current) return;
    if (conversations.length >= total && nextOffsetRef.current >= total) return;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    setLoadMoreError(null);
    setLoadMoreErrorAction(null);
    const seq = conversationSeq.current;
    const previousTotal = total;
    let merged = conversations;
    try {
      const offset = nextOffsetRef.current;
      if (offset >= total && merged.length < total) {
        const latest = await api.listConversations(0, 50);
        if (seq !== conversationSeq.current) return;
        merged = mergeConversations(merged, latest.items).items;
        setConversations(merged);
        setTotal(latest.total);
        nextOffsetRef.current = latest.items.length;
        setSyncNotice(recoveryNotice(merged.length, latest.total, latest.total !== previousTotal));
        return;
      }

      const data = await api.listConversations(offset, 50);
      if (seq !== conversationSeq.current) return;
      nextOffsetRef.current = offset + data.items.length;
      const page = mergeConversations(merged, data.items);
      merged = page.items;
      setConversations(merged);
      setTotal(data.total);

      if (merged.length >= data.total) {
        setSyncNotice(recoveryNotice(merged.length, data.total, data.total !== previousTotal));
        return;
      }

      const scanEnded = data.items.length === 0 || nextOffsetRef.current >= data.total;
      if (page.added === 0 || scanEnded) {
        // 重排会让 offset 窗口重复；扫描窗口耗尽仍缺项时，只做一次有界的最新页补齐。
        const latest = await api.listConversations(0, 50);
        if (seq !== conversationSeq.current) return;
        merged = mergeConversations(merged, latest.items).items;
        setConversations(merged);
        setTotal(latest.total);
        nextOffsetRef.current = latest.items.length;
        setSyncNotice(
          recoveryNotice(merged.length, latest.total, data.total !== previousTotal || latest.total !== previousTotal),
        );
      } else {
        setSyncNotice(null);
      }
    } catch (caught) {
      if (seq !== conversationSeq.current) return;
      setLoadMoreError(errorMessage(caught));
      setLoadMoreErrorAction('loadMore');
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, [conversations, loading, total]);

  const resyncConversations = useCallback(async () => {
    if (loading || loadingMoreRef.current) return;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    setLoadMoreError(null);
    setLoadMoreErrorAction(null);
    const seq = conversationSeq.current;
    try {
      const data = await api.listConversations(0, 50);
      if (seq !== conversationSeq.current) return;
      // 重新同步以服务端首屏为准重建列表：必须丢弃旧集合，
      // 否则数量恰好相等时仍会把已删除的旧 ID 留在列表里。
      const page = mergeConversations([], data.items);
      setConversations(page.items);
      setTotal(data.total);
      nextOffsetRef.current = data.items.length;
      if (page.items.length === data.total) {
        setSyncNotice(null);
      } else {
        setSyncNotice(
          `已重新同步最新位置（已显示 ${page.items.length} / 共 ${data.total}）。可继续加载更早会话或再次同步。`,
        );
      }
    } catch (caught) {
      if (seq !== conversationSeq.current) return;
      setLoadMoreError(errorMessage(caught));
      setLoadMoreErrorAction('resync');
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, [loading]);

  const retryFailedConversationLoad = useCallback(() => {
    if (loadMoreErrorAction === 'resync') {
      void resyncConversations();
      return;
    }
    void loadMoreConversations();
  }, [loadMoreConversations, loadMoreErrorAction, resyncConversations]);

  useEffect(() => {
    void reloadConversations();
  }, [reloadConversations]);

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  const confirmLogout = useCallback(async () => {
    setLogoutBusy(true);
    try {
      await logout();
      setLogoutOpen(false);
      navigate('/login', { replace: true });
    } catch (caught) {
      push(errorMessage(caught), 'error');
    } finally {
      setLogoutBusy(false);
    }
  }, [logout, navigate, push]);

  const confirmDelete = useCallback(async () => {
    if (!deleteTarget) return;
    setDeleteBusy(true);
    try {
      await api.deleteConversation(deleteTarget.id);
      setDeleteTarget(null);
      await reloadConversations();
      push('会话已删除');
      if (deleteTarget.id === activeId) navigate('/chat', { replace: true });
    } catch (caught) {
      push(errorMessage(caught), 'error');
    } finally {
      setDeleteBusy(false);
    }
  }, [activeId, deleteTarget, navigate, push, reloadConversations]);

  const context = useMemo<ShellContextValue>(
    () => ({
      conversations,
      conversationsLoading: loading,
      conversationsError: error,
      conversationsTotal: total,
      conversationsHasMore: conversations.length < total,
      conversationsLoadingMore: loadingMore,
      conversationsLoadMoreError: loadMoreError,
      reloadConversations,
      loadMoreConversations,
    }),
    [conversations, error, loadMoreConversations, loadMoreError, loading, loadingMore, reloadConversations, total],
  );

  const role = user?.role ?? 'employee';
  const displayName = user?.display_name ?? '';

  return (
    <div className="app-shell">
      <aside className="app-sidebar" aria-label="侧边栏">
        <SidebarContent
          conversations={conversations}
          loading={loading}
          error={error}
          total={total}
          hasMore={conversations.length < total}
          loadingMore={loadingMore}
          loadMoreError={loadMoreError}
          syncNotice={syncNotice}
          role={role}
          displayName={displayName}
          activeId={activeId}
          onDelete={setDeleteTarget}
          onLogout={() => setLogoutOpen(true)}
          onRetry={() => void reloadConversations()}
          onLoadMore={() => void loadMoreConversations()}
          onRetryLoadMore={retryFailedConversationLoad}
          onResync={() => void resyncConversations()}
        />
      </aside>

      <main className="app-main">
        <header className="topbar">
          <div className="topbar-left">
            <button
              type="button"
              className="icon-button menu-button"
              aria-label="打开菜单"
              onClick={() => setMobileOpen(true)}
            >
              <Icon name="menu" size={18} />
            </button>
            <h1 className="topbar-title">{isDocuments ? '资料管理' : 'AI 助手'}</h1>
            {isDocuments ? (
              <span className="topbar-badge">资料维护</span>
            ) : (
              <span className="topbar-badge">{roleLabel(role)}</span>
            )}
          </div>
          <div className="topbar-right">
            {isDocuments ? (
              <span className="badge badge-amber">
                <Icon name="shield-check" size={13} />
                管理员权限
              </span>
            ) : (
              <>
                <span className="sync-dot" aria-hidden="true" />
                <span className="sync-text">已登录 · {roleLabel(role)}</span>
                <span className="topbar-sep" aria-hidden="true">·</span>
                <span className="topbar-date">{formatDay(new Date().toISOString())}</span>
              </>
            )}
          </div>
        </header>
        <Outlet context={context} />
      </main>

      {mobileOpen ? (
        <>
          <div className="scrim" aria-hidden="true" onClick={() => setMobileOpen(false)} />
          <aside className="mobile-drawer" role="dialog" aria-modal="true" aria-label="导航与最近对话">
            <div className="mobile-drawer-head">
              <span className="brand-name">市场部 AI 知识库</span>
              <button type="button" className="icon-button" aria-label="关闭菜单" onClick={() => setMobileOpen(false)}>
                <Icon name="x" size={18} />
              </button>
            </div>
            <div style={{ display: 'flex', minHeight: 0, flex: 1, flexDirection: 'column' }}>
              <SidebarContent
                conversations={conversations}
                loading={loading}
                error={error}
                total={total}
                hasMore={conversations.length < total}
                loadingMore={loadingMore}
                loadMoreError={loadMoreError}
                syncNotice={syncNotice}
                role={role}
                displayName={displayName}
                activeId={activeId}
                onNavigate={() => setMobileOpen(false)}
                onDelete={(conversation) => {
                  setMobileOpen(false);
                  setDeleteTarget(conversation);
                }}
                onLogout={() => {
                  setMobileOpen(false);
                  setLogoutOpen(true);
                }}
                onRetry={() => void reloadConversations()}
                onLoadMore={() => void loadMoreConversations()}
                onRetryLoadMore={retryFailedConversationLoad}
                onResync={() => void resyncConversations()}
                hideBrand
              />
            </div>
          </aside>
        </>
      ) : null}

      {logoutOpen ? (
        <ConfirmDialog
          title="退出登录？"
          description="退出后需要重新登录才能继续使用 AI 知识库。"
          confirmLabel="退出登录"
          tone="default"
          busy={logoutBusy}
          onConfirm={() => void confirmLogout()}
          onCancel={() => setLogoutOpen(false)}
        />
      ) : null}

      {deleteTarget ? (
        <ConfirmDialog
          title="删除这条历史会话？"
          description={`将删除「${deleteTarget.title}」及其消息。删除后不再出现在本人历史列表中，不影响知识库资料。`}
          confirmLabel="删除会话"
          busy={deleteBusy}
          onConfirm={() => void confirmDelete()}
          onCancel={() => setDeleteTarget(null)}
        />
      ) : null}
    </div>
  );
}
