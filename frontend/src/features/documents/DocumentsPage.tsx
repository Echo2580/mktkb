import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import type { DocumentList, DocumentSummary, UploadResponse } from '../../api/client';
import { useAuth } from '../../app/AuthProvider';
import { Icon, fileIconFor } from '../../components/Icon';
import { ConfirmDialog } from '../../components/Dialog';
import { useToast } from '../../app/ToastProvider';
import {
  FILE_TYPE_LABELS,
  VERSION_STATE_LABELS,
  formatDateTime,
  versionTone,
} from '../../utils/format';
import { UploadDialog, type UploadTarget } from './UploadDialog';
import { FolderUploadDialog } from './FolderUploadDialog';
import { VersionDrawer } from './VersionDrawer';
import { loadJobRegistry, saveJobRegistry, type JobRegistry } from './jobRegistry';

const PAGE_SIZE = 20;
const STATE_OPTIONS = ['queued', 'processing', 'review_required', 'failed', 'published', 'superseded', 'cancelled'];

interface Notice {
  tone: 'success' | 'warning' | 'error' | 'info';
  message: string;
}

interface DrawerState {
  documentId: string;
  initialVersionId?: string;
}

interface DeleteTarget {
  id: string;
  name: string;
  revision: number;
}

const NOTICE_ICONS: Record<Notice['tone'], string> = {
  success: 'check-circle',
  warning: 'alert-circle',
  error: 'alert-circle',
  info: 'info',
};

function latestStateText(document: DocumentSummary): string {
  const latest = document.latest_version;
  const active = document.active_version;
  if (!latest) return '尚无版本';
  if (active && latest.id === active.id) return '当前版本已生效';
  const label = VERSION_STATE_LABELS[latest.state] ?? latest.state;
  return active
    ? `生效 V${active.number}／V${latest.number} ${label}`
    : `V${latest.number} ${label}，尚未生效`;
}

export function DocumentsPage() {
  const { user } = useAuth();
  const { push } = useToast();

  const [qInput, setQInput] = useState('');
  const [query, setQuery] = useState('');
  const [stateFilter, setStateFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<DocumentList | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [upload, setUpload] = useState<{ mode: 'create' | 'replace'; target?: UploadTarget } | null>(null);
  const [folderUpload, setFolderUpload] = useState(false);
  const [drawer, setDrawer] = useState<DrawerState | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [preparingDeleteId, setPreparingDeleteId] = useState<string | null>(null);
  const [jobRegistry, setJobRegistry] = useState<JobRegistry>(() => loadJobRegistry());

  const isAdmin = user?.role === 'admin';

  const loadList = useCallback(
    async (options: { quiet?: boolean } = {}) => {
      if (!options.quiet) setLoading(true);
      try {
        const result = await api.listDocuments({
          q: query || undefined,
          state: stateFilter || undefined,
          fileType: typeFilter || undefined,
          offset,
          limit: PAGE_SIZE,
        });
        setData(result);
        setLoadError(null);
      } catch (caught) {
        setLoadError(errorMessage(caught));
      } finally {
        if (!options.quiet) setLoading(false);
      }
    },
    [offset, query, stateFilter, typeFilter],
  );

  useEffect(() => {
    if (!isAdmin) return;
    void loadList();
  }, [isAdmin, loadList]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(qInput.trim());
      setOffset(0);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [qInput]);

  const hasPending = useMemo(
    () =>
      Boolean(
        data?.items.some((document) =>
          ['queued', 'processing'].includes(document.latest_version?.state ?? ''),
        ),
      ),
    [data],
  );

  useEffect(() => {
    if (!hasPending || !isAdmin) return;
    const timer = window.setInterval(() => {
      void loadList({ quiet: true });
    }, 2500);
    return () => window.clearInterval(timer);
  }, [hasPending, isAdmin, loadList]);

  const registerJob = useCallback((versionId: string, jobId: string) => {
    setJobRegistry((previous) => {
      const next = { ...previous, [versionId]: jobId };
      saveJobRegistry(next);
      return next;
    });
  }, []);

  const handleUploaded = useCallback(
    (receipt: UploadResponse) => {
      registerJob(receipt.version.id, receipt.job.id);
      setUpload(null);
      setOffset(0);
      setNotice({
        tone: 'warning',
        message: `已上传「${receipt.document.name}」V${receipt.version.number}，任务已排队（${receipt.job.state}）。处理完成后需检查并确认发布，期间旧有效版本继续生效。`,
      });
      void loadList();
    },
    [loadList, registerJob],
  );

  const handleDrawerChanged = useCallback(
    (message: string, tone: 'success' | 'error' = 'success') => {
      setNotice({ tone: tone === 'success' ? 'success' : 'error', message });
      void loadList({ quiet: true });
    },
    [loadList],
  );

  function handleFolderUploaded(receipts: UploadResponse[]) {
    setJobRegistry((previous) => {
      const next = { ...previous };
      for (const receipt of receipts) next[receipt.version.id] = receipt.job.id;
      saveJobRegistry(next);
      return next;
    });
    setOffset(0);
    setNotice({ tone: 'warning', message: `本批已上传 ${receipts.length} 个文件，任务已排队。请在处理完成后逐项检查并确认发布。` });
    void loadList();
  }

  function openVersionDrawer(document: DocumentSummary) {
    const latest = document.latest_version;
    const active = document.active_version;
    const initialVersionId =
      latest && active && latest.id !== active.id ? latest.id : latest?.id ?? active?.id ?? undefined;
    setDrawer({ documentId: document.id, initialVersionId });
  }

  function openReplace(document: DocumentSummary) {
    setUpload({
      mode: 'replace',
      target: {
        id: document.id,
        name: document.name,
        activeVersionId: document.active_version?.id ?? null,
        activeVersionNumber: document.active_version?.number ?? null,
      },
    });
  }

  async function prepareDelete(document: DocumentSummary) {
    setPreparingDeleteId(document.id);
    try {
      const detail = await api.getDocument(document.id);
      setDeleteTarget({ id: document.id, name: document.name, revision: detail.revision });
    } catch (caught) {
      push(errorMessage(caught), 'error');
    } finally {
      setPreparingDeleteId(null);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeleteBusy(true);
    try {
      await api.deleteDocument(deleteTarget.id, deleteTarget.revision);
      setNotice({
        tone: 'success',
        message: `「${deleteTarget.name}」已删除。其内容与原件不再对问答与来源入口开放。`,
      });
      setDeleteTarget(null);
      if (drawer?.documentId === deleteTarget.id) setDrawer(null);
      await loadList({ quiet: true });
      push('资料已删除');
    } catch (caught) {
      push(errorMessage(caught), 'error');
      await loadList({ quiet: true });
    } finally {
      setDeleteBusy(false);
    }
  }

  if (!isAdmin) {
    return (
      <div className="page-scroll">
        <div className="page page-admin">
          <div className="notice notice-error" role="alert">
            <Icon name="shield-check" size={16} className="notice-icon" />
            <div className="notice-body">
              <p style={{ fontWeight: 600 }}>资料管理仅限管理员</p>
              <p style={{ marginTop: 4 }}>
                当前账号是员工角色，服务端会拒绝资料管理接口。员工可以查询已发布资料、查看来源并管理自己的会话。
              </p>
              <div className="notice-actions">
                <Link className="btn btn-primary btn-sm" to="/chat">
                  返回 AI 助手
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="page-scroll">
      <div className="page page-admin">
        <section className="mobile-admin-notice" aria-labelledby="mobile-admin-title">
          <div className="card">
            <div className="card-body">
              <span className="empty-icon">
                <Icon name="files" size={20} />
              </span>
              <h2 className="empty-title" id="mobile-admin-title" style={{ marginTop: 4 }}>
                资料管理请在电脑上使用
              </h2>
              <p className="empty-desc" style={{ maxWidth: 420 }}>
                手机端支持登录、问答、个人会话与来源查看。上传、检查、发布、替换和删除资料需要更大的屏幕和键盘操作，请使用电脑访问。
              </p>
              <div className="state-actions">
                <Link className="btn btn-primary btn-md" to="/chat">
                  <Icon name="sparkles" size={13} />
                  返回 AI 助手
                </Link>
              </div>
            </div>
          </div>
        </section>

        <div className="doc-desktop">
          <div className="page-header">
            <div>
              <h2 className="page-title">资料管理</h2>
              <p className="page-desc">上传后先检查提取内容，确认发布后才会参与 AI 问答。</p>
            </div>
            <div className="page-actions">
              <Link className="btn btn-secondary" to="/chat">
                <Icon name="sparkles" size={15} />
                返回 AI 助手
              </Link>
              <button type="button" className="btn btn-primary" onClick={() => setUpload({ mode: 'create' })}>
                <Icon name="upload" size={15} />
                上传资料
              </button>
              <button type="button" className="btn btn-secondary" onClick={() => setFolderUpload(true)}>
                <Icon name="folder" size={15} />
                上传文件夹
              </button>
            </div>
          </div>

          {notice ? (
            <div className={`notice notice-${notice.tone} notice-area`} role={notice.tone === 'error' ? 'alert' : 'status'}>
              <Icon name={NOTICE_ICONS[notice.tone]} size={15} className="notice-icon" />
              <div className="notice-body">
                <p>{notice.message}</p>
              </div>
              <button type="button" className="icon-button" aria-label="关闭提示" onClick={() => setNotice(null)}>
                <Icon name="x" size={14} />
              </button>
            </div>
          ) : null}

          <div style={{ marginTop: 20 }} className="card">
            <div className="doc-toolbar">
              <div className="filter-row">
                <div className="search-field">
                  <Icon name="search" size={15} className="search-icon" />
                  <input
                    className="search-input"
                    type="search"
                    aria-label="按文件名搜索"
                    placeholder="搜索文件名"
                    value={qInput}
                    onChange={(event) => setQInput(event.target.value)}
                  />
                </div>
                <select
                  className="filter-select"
                  aria-label="按状态筛选"
                  value={stateFilter}
                  onChange={(event) => {
                    setStateFilter(event.target.value);
                    setOffset(0);
                  }}
                >
                  <option value="">全部状态</option>
                  {STATE_OPTIONS.map((state) => (
                    <option key={state} value={state}>
                      {VERSION_STATE_LABELS[state] ?? state}
                    </option>
                  ))}
                </select>
                <select
                  className="filter-select"
                  aria-label="按文件类型筛选"
                  value={typeFilter}
                  onChange={(event) => {
                    setTypeFilter(event.target.value);
                    setOffset(0);
                  }}
                >
                  <option value="">全部类型</option>
                  <option value="xlsx">Excel</option>
                  <option value="docx">Word</option>
                  <option value="pdf">PDF</option>
                  <option value="png">图片 PNG</option>
                  <option value="jpg">图片 JPG</option>
                </select>
              </div>
              <p className="record-count">
                共 <strong>{total}</strong> 份资料 · 新版需确认发布后生效
              </p>
            </div>

            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">文件名</th>
                    <th scope="col">类型</th>
                    <th scope="col">当前生效版本</th>
                    <th scope="col">新版处理状态</th>
                    <th scope="col">最近生效时间</th>
                    <th scope="col" style={{ textAlign: 'right' }}>
                      操作
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {loading && !data ? (
                    <tr>
                      <td colSpan={6}>
                        <div className="empty-state" role="status">
                          <span className="spinner" aria-hidden="true" />
                          <p className="empty-desc" style={{ marginTop: 8 }}>
                            正在加载资料列表…
                          </p>
                        </div>
                      </td>
                    </tr>
                  ) : loadError ? (
                    <tr>
                      <td colSpan={6}>
                        <div className="notice notice-error" style={{ margin: 16 }} role="alert">
                          <Icon name="alert-circle" size={15} className="notice-icon" />
                          <div className="notice-body">
                            <p>{loadError}</p>
                            <div className="notice-actions">
                              <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadList()}>
                                重试
                              </button>
                            </div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  ) : data && data.items.length === 0 ? (
                    <tr>
                      <td colSpan={6}>
                        <div className="empty-state">
                          <span className="empty-icon">
                            <Icon name={query || stateFilter || typeFilter ? 'search-x' : 'inbox'} size={20} />
                          </span>
                          <p className="empty-title">
                            {query || stateFilter || typeFilter ? '没有匹配的资料' : '还没有资料'}
                          </p>
                          <p className="empty-desc">
                            {query || stateFilter || typeFilter
                              ? '调整文件名或筛选条件后重试。'
                              : '上传第一份资料；处理完成后检查并确认发布，员工问答才会使用。'}
                          </p>
                        </div>
                      </td>
                    </tr>
                  ) : (
                    (data?.items ?? []).map((document) => {
                      const latest = document.latest_version;
                      const active = document.active_version;
                      const meta = fileIconFor(document.name);
                      const latestIsActive = Boolean(latest && active && latest.id === active.id);
                      return (
                        <tr key={document.id}>
                          <td>
                            <div className="file-cell">
                              <span className={`tile ${meta.tile}`}>
                                <Icon name={meta.icon} size={16} />
                              </span>
                              <span className="file-texts">
                                <span className="file-name" title={document.name}>
                                  {document.name}
                                </span>
                                <span className="file-sub">
                                  {latest ? `最近上传 ${formatDateTime(latest.uploaded_at)}` : '尚无版本'}
                                </span>
                                {latest?.state === 'failed' ? (
                                  <span className="file-sub is-error">最新版处理失败，打开检查查看原因</span>
                                ) : null}
                              </span>
                            </div>
                          </td>
                          <td>
                            <span className={`badge ${meta.badge}`}>{FILE_TYPE_LABELS[document.file_type] ?? meta.label}</span>
                          </td>
                          <td className="version-cell">
                            {active ? (
                              <>
                                <span className="version-strong">V{active.number}</span>
                                <span className="version-note">生效中</span>
                              </>
                            ) : (
                              <span className="pending-note">尚未生效</span>
                            )}
                          </td>
                          <td>
                            {!latest || latestIsActive ? (
                              <span className="pending-empty">
                                <span className="badge-dot" />
                                {latest ? '当前版本已生效' : '尚无版本'}
                              </span>
                            ) : (
                              <div className="pending-cell">
                                <span className={`badge badge-${versionTone(latest.state)}`}>
                                  <span className="badge-dot" />V{latest.number} {VERSION_STATE_LABELS[latest.state] ?? latest.state}
                                </span>
                                <span className="pending-note">{latestStateText(document)}</span>
                              </div>
                            )}
                          </td>
                          <td className="nowrap" style={{ color: 'var(--slate-500)', fontSize: 12 }}>
                            {formatDateTime(document.last_published_at)}
                          </td>
                          <td>
                            <div className="row-actions">
                              <button type="button" className="btn btn-ghost btn-sm" onClick={() => openVersionDrawer(document)}>
                                查看/检查
                              </button>
                              <button type="button" className="btn btn-ghost btn-sm" onClick={() => openReplace(document)}>
                                替换
                              </button>
                              <button
                                type="button"
                                className="btn btn-danger-ghost btn-sm"
                                onClick={() => void prepareDelete(document)}
                                disabled={preparingDeleteId === document.id}
                              >
                                {preparingDeleteId === document.id ? '读取中…' : '删除'}
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            <div className="pagination">
              <span className="page-info">
                第 {currentPage} / {totalPages} 页 · 共 {total} 份
              </span>
              <div className="page-buttons">
                <button
                  type="button"
                  className="btn btn-secondary btn-md"
                  disabled={offset <= 0 || loading}
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                >
                  <Icon name="chevron-left" size={13} />
                  上一页
                </button>
                <button
                  type="button"
                  className="btn btn-secondary btn-md"
                  disabled={offset + PAGE_SIZE >= total || loading}
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                >
                  下一页
                  <Icon name="chevron-right" size={13} />
                </button>
              </div>
            </div>
          </div>

          <p className="doc-footnote">
            <Icon name="info" size={13} />
            <span>
              新版处理中或处理失败时，旧版本继续生效；问答引用以当前生效版本为准。列表只显示未删除资料，已删除资料不会出现在这里。
            </span>
          </p>
        </div>
      </div>

      {folderUpload ? <FolderUploadDialog onClose={() => setFolderUpload(false)} onUploaded={handleFolderUploaded} /> : null}

      {upload ? (
        <UploadDialog
          mode={upload.mode}
          target={upload.target}
          onClose={() => setUpload(null)}
          onUploaded={handleUploaded}
        />
      ) : null}

      {drawer ? (
        <VersionDrawer
          documentId={drawer.documentId}
          initialVersionId={drawer.initialVersionId}
          jobRegistry={jobRegistry}
          onClose={() => setDrawer(null)}
          onChanged={handleDrawerChanged}
          onJobKnown={registerJob}
        />
      ) : null}

      {deleteTarget ? (
        <ConfirmDialog
          title="删除此资料？"
          description={`将删除「${deleteTarget.name}」及其全部版本。删除生效后，AI 助手无法再引用该资料，历史来源只保留失效状态，原件与提取内容不可访问。此操作不可撤销。`}
          confirmLabel="删除资料"
          busy={deleteBusy}
          onConfirm={() => void confirmDelete()}
          onCancel={() => setDeleteTarget(null)}
        />
      ) : null}
    </div>
  );
}
