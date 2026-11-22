/**
 * T304 问答诊断页（原 RequestsPlaceholderPage 完整实现，文件名与导出名保持不变）。
 *
 * 组成：结果筛选 + 游标分页列表 + 诊断抽屉（含执行阶段条）+ 固定评测页签。
 * 只读：不发起问答、不发起评测、不打开他人会话。
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, ApiError } from '../../api/client';
import type { RequestListItem } from './qa/qaApi';
import { useAuth } from '../../app/AuthProvider';
import { Icon } from '../../components/Icon';import {
  RESULT_KINDS,
  applyWindow,
  overviewQuery,
  readFilters,
  resolveWindow,
  toSearch,
  toSearchParams,
  todayInShanghai,
  windowLabel,
  WINDOW_KEYS,
  WINDOW_LABELS,
  type OperationsFilters,
  type WindowKey,
} from './filters';
import { DiagnosisDrawer } from './qa/DiagnosisDrawer';
import { EvalRunsPanel } from './qa/EvalRunsPanel';
import { formatMoment, isDemoEnvironment, kindMeta, shortId } from './qa/qaMeta';
import './operations.css';
import './qa/qa.css';

const PAGE_SIZE = 20;
const MAX_PAGES = 20;

type TabKey = 'records' | 'eval';

function tabFrom(searchParams: URLSearchParams): TabKey {
  return searchParams.get('tab') === 'eval' ? 'eval' : 'records';
}

export function OperationsRequestsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => readFilters(searchParams), [searchParams]);
  const filterKey = toSearch(filters);
  const tab = tabFrom(searchParams);
  const requestId = searchParams.get('request_id') ?? '';
  const today = todayInShanghai();
  const resolved = resolveWindow(filters, today);
  const rangeError = resolved.error ?? null;
  const kindInvalid = Boolean(filters.kind) && !(RESULT_KINDS as readonly string[]).includes(filters.kind);
  const demoEnvironment = isDemoEnvironment();

  const [items, setItems] = useState<RequestListItem[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [pages, setPages] = useState(0);
  const [truncated, setTruncated] = useState(false);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [sinceDraft, setSinceDraft] = useState(filters.since);
  const [untilDraft, setUntilDraft] = useState(filters.until);
  const sequence = useRef(0);

  useEffect(() => {
    setSinceDraft(filters.since);
    setUntilDraft(filters.until);
  }, [filters.since, filters.until]);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [filterKey]);

  useEffect(() => {
    if (!isAdmin || tab !== 'records') return undefined;
    if (rangeError) {
      setListLoading(false);
      setListError(rangeError);
      return undefined;
    }
    if (kindInvalid) {
      setListLoading(false);
      setListError('结果类型不在六类范围内，请返回总览重新选择。');
      return undefined;
    }
    const ticket = sequence.current + 1;
    sequence.current = ticket;
    let cancelled = false;
    setListLoading(true);
    setListError(null);
    setItems([]);
    setTotal(null);
    setPages(0);
    setTruncated(false);

    (async () => {
      const collected: RequestListItem[] = [];
      let cursor: string | undefined;
      let pageCount = 0;
      let more = false;
      for (;;) {
        const page = await api.operationsRequests({
          ...overviewQuery(filters, today),
          kind: filters.kind || undefined,
          documentId: filters.documentId || undefined,
          versionId: filters.versionId || undefined,
          cursor,
          pageSize: PAGE_SIZE,
        });
        if (cancelled || sequence.current !== ticket) return;
        collected.push(...(page.items ?? []));
        pageCount += 1;
        cursor = page.next_cursor ?? undefined;
        if (!cursor) break;
        if (pageCount >= MAX_PAGES) {
          more = true;
          break;
        }
      }
      // 游标分页理论上不重复；这里再按 request_id 去重兜底，保证「无重复无漏项」。
      const seen = new Set<string>();
      const unique = collected.filter((row) => {
        if (seen.has(row.request_id)) return false;
        seen.add(row.request_id);
        return true;
      });
      setItems(unique);
      setTotal(unique.length);
      setPages(pageCount);
      setTruncated(more);
      setListLoading(false);
    })().catch((caught: unknown) => {
      if (cancelled || sequence.current !== ticket) return;
      setItems([]);
      setTotal(null);
      setListLoading(false);
      if (caught instanceof ApiError) {
        if (caught.status === 403) setListError('当前账号无权访问运营数据。');
        else if (caught.status === 422) setListError('筛选参数不合法，请返回总览重新选择。');
        else setListError(caught.message || '运营接口请求失败');
      } else {
        setListError(caught instanceof Error ? caught.message : '运营接口请求失败');
      }
    });
    return () => {
      cancelled = true;
    };
  }, [filterKey, tab, isAdmin, retryKey, kindInvalid, rangeError]);

  if (!isAdmin) {
    return (
      <div className="page-scroll">
        <div className="page page-admin">
          <div className="notice notice-error" role="alert">
            <Icon name="shield-check" size={16} className="notice-icon" />
            <div className="notice-body">
              <p style={{ fontWeight: 600 }}>知识运营仅限管理员</p>
              <p style={{ marginTop: 4 }}>当前账号是员工角色，服务端会拒绝运营只读接口。</p>
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

  /** 筛选唯一写入口：保留 tab，丢弃抽屉参数（明细与筛选各自独立）。 */
  function updateFilters(next: OperationsFilters) {
    setSearchParams((prev) => {
      const params = toSearchParams(next);
      const previousTab = prev.get('tab');
      if (previousTab) params.set('tab', previousTab);
      return params;
    });
  }

  function switchTab(next: TabKey) {
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev);
      if (next === 'records') params.delete('tab');
      else params.set('tab', 'eval');
      params.delete('request_id');
      return params;
    });
  }

  function openRequest(id: string) {
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev);
      params.set('request_id', id);
      return params;
    });
  }

  function closeRequest() {
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev);
      params.delete('request_id');
      return params;
    });
  }

  function clearDocumentFilter() {
    updateFilters({ ...filters, documentId: '', versionId: '' });
  }

  function resetFilters() {
    updateFilters({ window: '7d', since: '', until: '', kind: '', documentId: '', versionId: '', state: '' });
  }

  const overviewTab = `/operations?${filterKey}`;
  const documentsTab = `/operations/documents?${filterKey}`;
  const visible = items.slice(0, visibleCount);
  const hasMore = visibleCount < items.length;
  const openFinishedAt = items.find((row) => row.request_id === requestId)?.finished_at ?? null;
  const customInvalid =
    filters.window === 'custom' &&
    (!sinceDraft || !untilDraft || Boolean(resolveWindow({ ...filters, since: sinceDraft, until: untilDraft }, today).error));

  return (
    <div className="page-scroll">
      <div className="page page-admin">
        <div className="page-header">
          <div>
            <h2 className="page-title">知识运营</h2>
            <p className="page-desc">逐条查看问答结果、引用版本与执行过程，异常记录可回溯到具体资料。</p>
          </div>
          <div className="page-actions">
            <span className="badge badge-slate">只读工作台</span>
            {demoEnvironment ? <span className="ops-demo-badge">示例数据</span> : null}
            <Link className="btn btn-secondary btn-sm" to={overviewTab}>
              <Icon name="arrow-left" size={14} /> 返回总览
            </Link>
          </div>
        </div>

        <nav className="ops-tabs" aria-label="运营工作台页面">
          <Link className="ops-tab" to={overviewTab}>
            运营总览
          </Link>
          <Link className="ops-tab" to={`/operations/requests?${filterKey}`} aria-current="page">
            问答诊断
          </Link>
          <Link className="ops-tab" to={documentsTab}>
            知识资产
          </Link>
        </nav>

        <div className="qa-seg-row">
          <div className="qa-seg" role="group" aria-label="问答诊断视图">
            <button
              type="button"
              className={`qa-seg-btn${tab === 'records' ? ' is-active' : ''}`}
              aria-pressed={tab === 'records'}
              data-testid="qa-tab-records"
              onClick={() => switchTab('records')}
            >
              问答记录
            </button>
            <button
              type="button"
              className={`qa-seg-btn${tab === 'eval' ? ' is-active' : ''}`}
              aria-pressed={tab === 'eval'}
              data-testid="qa-tab-eval"
              onClick={() => switchTab('eval')}
            >
              固定评测
            </button>
          </div>
          <p className="qa-seg-note">异常与冲突记录可逐条回溯到资料与执行过程</p>
        </div>

        {tab === 'records' ? (
          <section aria-label="问答记录" data-testid="qa-records-panel">
            {filters.documentId || filters.versionId ? (
              <div className="qa-banner" data-testid="qa-asset-banner" role="status">
                <span>
                  已按资料筛选问答记录：文档 {shortId(filters.documentId) || '未指定'}
                  {filters.versionId ? ` · 版本 ${shortId(filters.versionId)}` : ''}
                  （列表接口未返回资料名称，按文档标识展示）
                </span>
                <button type="button" className="qa-link-btn" data-testid="qa-clear-document" onClick={clearDocumentFilter}>
                  清除筛选
                </button>
              </div>
            ) : null}

            <div className="qa-filter-bar" data-testid="qa-filter-bar">
              <div className="qa-filter-group">
                <span className="qa-filter-label">窗口</span>
                {WINDOW_KEYS.map((key: WindowKey) => (
                  <button
                    key={key}
                    type="button"
                    className={`btn btn-sm ${filters.window === key ? 'btn-primary' : 'btn-secondary'}`}
                    aria-pressed={filters.window === key}
                    data-window-option={key}
                    onClick={() => updateFilters(applyWindow(filters, key))}
                  >
                    {WINDOW_LABELS[key]}
                  </button>
                ))}
                {filters.window === 'custom' ? (
                  <span className="qa-custom-range">
                    <label className="qa-date-label">
                      开始
                      <input
                        type="date"
                        className="filter-select"
                        value={sinceDraft}
                        max={untilDraft || today}
                        onChange={(event) => setSinceDraft(event.target.value)}
                      />
                    </label>
                    <label className="qa-date-label">
                      结束
                      <input
                        type="date"
                        className="filter-select"
                        value={untilDraft}
                        min={sinceDraft || undefined}
                        max={today}
                        onChange={(event) => setUntilDraft(event.target.value)}
                      />
                    </label>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={customInvalid}
                      onClick={() => updateFilters(applyWindow(filters, 'custom', { since: sinceDraft, until: untilDraft }))}
                    >
                      应用
                    </button>
                  </span>
                ) : null}
              </div>

              <div className="qa-filter-group">
                <label className="qa-filter-label" htmlFor="qa-kind-filter">
                  结果
                </label>
                <select
                  id="qa-kind-filter"
                  className="filter-select"
                  data-testid="qa-kind-filter"
                  value={filters.kind}
                  onChange={(event) => updateFilters({ ...filters, kind: event.target.value })}
                >
                  <option value="">全部结果</option>
                  {RESULT_KINDS.map((kind) => (
                    <option key={kind} value={kind}>
                      {kindMeta(kind).label}
                    </option>
                  ))}
                </select>
                <button type="button" className="btn btn-secondary btn-sm" data-testid="qa-reset" onClick={resetFilters}>
                  重置
                </button>
              </div>
            </div>

            <div className="qa-summary-bar">
              {listLoading ? (
                <p className="qa-loading" role="status" data-testid="qa-list-loading">
                  <span className="spinner spinner-sm" aria-hidden="true" /> 正在按游标加载问答记录…
                </p>
              ) : listError ? (
                <span className="qa-summary-error">加载失败</span>
              ) : (
                <div data-testid="ops-placeholder-ready" className="qa-summary-inner">
                  <p className="qa-summary" data-testid="qa-total-line">
                    当前筛选共 <strong data-testid="ops-placeholder-total">{total ?? 0}</strong> 条
                    <span className="qa-summary-sub">
                      （按 next_cursor 累计 {pages} 页；单页 {PAGE_SIZE} 条
                      {truncated ? `，已达 ${MAX_PAGES} 页上限，总数可能不完整` : ''}）
                    </span>
                  </p>
                  <p className="qa-summary-meta">
                    <span data-testid="ops-placeholder-kind">
                      结果：{filters.kind ? `${filters.kind}（${kindMeta(filters.kind).label}）` : '全部'}
                    </span>
                    <span> · {windowLabel(filters, today)}</span>
                  </p>
                </div>
              )}
            </div>

            {rangeError || kindInvalid ? (
              <p className="ops-inline-error" role="alert" data-testid="qa-filter-error">
                {rangeError ?? '结果类型不在六类范围内，请返回总览重新选择。'}
              </p>
            ) : null}

            {listError && !listLoading ? (
              <div className="notice notice-error" role="alert" data-testid="qa-error">
                <Icon name="alert-circle" size={16} className="notice-icon" />
                <div className="notice-body">
                  <p style={{ fontWeight: 600 }}>问答记录加载失败</p>
                  <p style={{ marginTop: 4 }}>{listError}</p>
                  <div className="notice-actions">
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      data-testid="qa-retry"
                      onClick={() => setRetryKey((value) => value + 1)}
                    >
                      重试
                    </button>
                  </div>
                </div>
              </div>
            ) : null}

            {!listLoading && !listError ? (
              items.length === 0 ? (
                <div className="empty-state qa-empty" data-testid="qa-empty">
                  <h4 className="empty-title">当前筛选条件下没有问答记录</h4>
                  <p className="empty-desc">窗口内没有已提交结果的问答；可放宽日期或结果类型。</p>
                  <button type="button" className="btn btn-secondary btn-sm" onClick={resetFilters}>
                    清除筛选
                  </button>
                </div>
              ) : (
                <>
                  <div className="qa-table-wrap">
                    <table className="qa-table" data-testid="qa-table">
                      <thead>
                        <tr>
                          <th scope="col" className="qa-col-time">
                            时间
                          </th>
                          <th scope="col">请求标识</th>
                          <th scope="col" className="qa-col-kind">
                            结果
                          </th>
                          <th scope="col" className="qa-col-citations">
                            引用数
                          </th>
                          <th scope="col" className="qa-col-action">
                            操作
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {visible.map((row) => {
                          const meta = kindMeta(row.kind);
                          return (
                            <tr
                              key={row.request_id}
                              className="qa-row"
                              tabIndex={0}
                              data-testid="qa-row"
                              data-request-id={row.request_id}
                              data-kind={row.kind ?? ''}
                              aria-label={`查看问答诊断 ${shortId(row.request_id)}`}
                              onClick={() => openRequest(row.request_id)}
                              onKeyDown={(event) => {
                                if (event.key === 'Enter' || event.key === ' ') {
                                  event.preventDefault();
                                  openRequest(row.request_id);
                                }
                              }}
                            >
                              <td className="qa-cell-time">{formatMoment(row.finished_at)}</td>
                              <td>
                                <span className="qa-request-id">{shortId(row.request_id)}</span>
                                {row.conflict_flag ? <span className="qa-badge is-conflict">存在冲突来源</span> : null}
                              </td>
                              <td>
                                <span className={`qa-badge is-${meta.tone}`} data-result-kind={row.kind ?? ''}>
                                  {meta.label}
                                </span>
                              </td>
                              <td>
                                {row.citation_count > 0 ? (
                                  <span className="qa-citation-count">{row.citation_count} 份</span>
                                ) : (
                                  <span className="qa-muted">未引用资料</span>
                                )}
                              </td>
                              <td className="qa-cell-action">
                                <button
                                  type="button"
                                  className="qa-table-action"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    openRequest(row.request_id);
                                  }}
                                >
                                  查看诊断 <Icon name="arrow-right" size={14} />
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>

                  <div className="qa-list-foot">
                    {hasMore ? (
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        data-testid="qa-load-more"
                        onClick={() => setVisibleCount((value) => value + PAGE_SIZE)}
                      >
                        加载更多（已显示 {visible.length} / {items.length} 条）
                      </button>
                    ) : (
                      <p className="qa-list-note" data-testid="qa-list-complete">
                        已加载全部 {items.length} 条记录
                      </p>
                    )}
                    <p className="qa-list-note">统计口径为问答结束时间（Asia/Shanghai）；列表按完成时间与请求 ID 确定性排序。</p>
                  </div>
                </>
              )
            ) : null}
          </section>
        ) : (
          <EvalRunsPanel />
        )}

        <footer className="ops-footer">
          <span>问答诊断为只读记录 · 阶段与耗时按实际记录展示，未记录不补 0</span>
          {demoEnvironment ? <span className="ops-footer-env">演示环境 · 受控样本数据</span> : null}
        </footer>
      </div>

      {requestId ? (
        <DiagnosisDrawer requestId={requestId} finishedAt={openFinishedAt} onClose={closeRequest} />
      ) : null}
    </div>
  );
}
