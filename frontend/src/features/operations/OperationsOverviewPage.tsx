import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, ApiError } from '../../api/client';
import type { OperationsOverview } from '../../api/client';
import { useAuth } from '../../app/AuthProvider';
import { Icon } from '../../components/Icon';
import {
  DEFAULT_WINDOW,
  MAX_WINDOW_DAYS,
  RESULT_KINDS,
  RESULT_LABELS,
  WINDOW_KEYS,
  WINDOW_LABELS,
  applyWindow,
  drillToDay,
  drillToKind,
  overviewQuery,
  readFilters,
  requestsPath,
  documentsPath,
  resolveWindow,
  toSearch,
  toSearchParams,
  todayInShanghai,
  windowLabel,
  type OperationsFilters,
  type WindowKey,
} from './filters';
import { distributionOption, trendOption } from './charts';
import { EChart } from './EChart';
import './operations.css';

const TRACE_STATUS_LABELS: Record<string, string> = {
  recorded: '已记录',
  partial: '部分覆盖',
  disabled: 'Trace 已关闭',
  unavailable: 'Trace 暂不可用',
  not_recorded: '未记录',
};

function traceStatusText(coverage: OperationsOverview['trace_coverage']): string {
  const status = coverage.status ?? '';
  const label = TRACE_STATUS_LABELS[status] ?? '状态未知';
  if (
    (status === 'recorded' || status === 'partial') &&
    typeof coverage.covered === 'number' &&
    typeof coverage.total === 'number'
  ) {
    return `${label} · ${coverage.covered}/${coverage.total}`;
  }
  return label;
}

function formatMoment(value?: string | null): string {
  if (!value) return '时间未记录';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date);
  const pick = (type: string) => parts.find((part) => part.type === type)?.value ?? '';
  return `${pick('month')}-${pick('day')} ${pick('hour')}:${pick('minute')}`;
}

function shareText(part: number, total: number): string {
  if (total <= 0) return '无样本';
  if (part <= 0) return '占全部问答 0%';
  return `占全部问答 ${((part / total) * 100).toFixed(1)}%`;
}

function answeredText(part: number, total: number): string {
  if (total <= 0) return '无样本';
  if (part <= 0) return '已回答占 0%';
  return `已回答占 ${((part / total) * 100).toFixed(1)}%`;
}

function isDemoEnvironment(): boolean {
  if (typeof window === 'undefined') return false;
  return window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost';
}

function shortId(value?: string | null): string {
  if (!value) return '';
  return value.length > 8 ? `${value.slice(0, 8)}…` : value;
}

type PendingItem = NonNullable<OperationsOverview['pending']>[number];

function pendingKindLabel(item: PendingItem): string {
  return RESULT_LABELS[item.kind as keyof typeof RESULT_LABELS] ?? item.kind ?? '问答异常';
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;
}

export function OperationsOverviewPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => readFilters(searchParams), [searchParams]);
  const filterKey = toSearch(filters);

  const [data, setData] = useState<OperationsOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const [sinceDraft, setSinceDraft] = useState(filters.since);
  const [untilDraft, setUntilDraft] = useState(filters.until);
  const sequence = useRef(0);

  const today = todayInShanghai();
  const resolved = resolveWindow(filters, today);
  const label = windowLabel(filters, today);
  const rangeInvalid = Boolean(resolved.error);
  const demoEnvironment = isDemoEnvironment();
  const overviewTab = `/operations?${filterKey}`;
  const requestsTab = requestsPath(filters);
  const documentsTab = documentsPath(filters);
  const spanDays =
    resolved.since && resolved.until
      ? Math.round((Date.parse(`${resolved.until}T00:00:00Z`) - Date.parse(`${resolved.since}T00:00:00Z`)) / 86400000) + 1
      : 0;
  const distributionLead = filters.window === 'today' ? '今日' : `近 ${spanDays || 7} 天`;

  useEffect(() => {
    setSinceDraft(filters.since);
    setUntilDraft(filters.until);
  }, [filters.since, filters.until]);

  useEffect(() => {
    if (!isAdmin) return undefined;
    if (resolved.error) {
      setData(null);
      setLoading(false);
      setLoadError(resolved.error);
      return undefined;
    }
    const ticket = sequence.current + 1;
    sequence.current = ticket;
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    api
      .operationsOverview(overviewQuery(filters, today))
      .then((result) => {
        if (cancelled || sequence.current !== ticket) return;
        setData(result);
        setLoading(false);
      })
      .catch((caught: unknown) => {
        if (cancelled || sequence.current !== ticket) return;
        setData(null);
        setLoading(false);
        if (caught instanceof ApiError) {
          if (caught.status === 403) setLoadError('当前账号无权访问运营数据，请使用管理员账号。');
          else if (caught.status === 422) setLoadError('日期窗口不合法，请检查起止日期（最长 90 天）。');
          else setLoadError(caught.message || '运营接口请求失败');
        } else {
          setLoadError(caught instanceof Error ? caught.message : '运营接口请求失败');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [filterKey, isAdmin, rangeInvalid, retryKey]);

  if (!isAdmin) {
    return (
      <div className="page-scroll">
        <div className="page page-admin">
          <div className="notice notice-error" role="alert">
            <Icon name="shield-check" size={16} className="notice-icon" />
            <div className="notice-body">
              <p style={{ fontWeight: 600 }}>知识运营仅限管理员</p>
              <p style={{ marginTop: 4 }}>
                当前账号是员工角色，服务端会拒绝运营只读接口。员工可以继续使用 AI 助手查询已发布资料。
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

  /** 筛选唯一写入口：所有切换、图表点击、键盘按钮都走这里。 */
  function updateFilters(next: OperationsFilters) {
    setSearchParams(toSearchParams(next));
  }

  function goDay(day: string) {
    navigate(requestsPath(drillToDay(filters, day)));
  }

  function goKind(kind: string) {
    navigate(requestsPath(drillToKind(filters, kind)));
  }

  function goRequestPending(item: NonNullable<OperationsOverview['pending']>[number]) {
    const day = item.drilldown?.date ?? null;
    const kind = item.drilldown?.kind ?? item.kind ?? null;
    const next: OperationsFilters = {
      ...filters,
      window: day ? 'custom' : filters.window,
      since: day ?? filters.since,
      until: day ?? filters.until,
      kind: kind ?? '',
    };
    navigate(requestsPath(next));
  }

  function goImportPending(item: NonNullable<OperationsOverview['pending']>[number]) {
    const documentId = item.drilldown?.document_id ?? item.document_id ?? '';
    const versionId = item.drilldown?.version_id ?? item.version_id ?? '';
    const state = item.drilldown?.state ?? item.state ?? '';
    navigate(
      documentsPath({
        ...filters,
        documentId,
        versionId,
        state,
        kind: '',
      }),
    );
  }

  const metrics = data?.metrics;
  const trend = data?.trend ?? [];
  const distribution = data?.result_distribution ?? {};
  const distributionValues = RESULT_KINDS.reduce<Record<string, number>>((acc, kind) => {
    acc[kind] = Number(distribution[kind] ?? 0);
    return acc;
  }, {});
  const distributionTotal = RESULT_KINDS.reduce((sum, kind) => sum + distributionValues[kind], 0);
  const pending = data?.pending ?? [];
  const animation = !prefersReducedMotion();

  const customInvalid =
    filters.window === 'custom' &&
    (!sinceDraft || !untilDraft || resolveWindow({ ...filters, since: sinceDraft, until: untilDraft }, today).error);

  return (
    <div className="page-scroll">
      <div className="page page-admin">
        <div className="page-header">
          <div>
            <h2 className="page-title">知识运营</h2>
            <p className="page-desc">查看问答效果、异常分布与知识资产状态；资料处理请前往资料管理。</p>
          </div>
          <div className="page-actions">
            <Link className="ops-header-link" to="/documents">
              前往资料管理 <Icon name="arrow-right" size={14} />
            </Link>
            <span className="badge badge-slate">只读工作台</span>
            {demoEnvironment ? <span className="ops-demo-badge">示例数据</span> : null}
          </div>
        </div>

        <nav className="ops-tabs" aria-label="运营工作台页面">
          <Link className="ops-tab" to={overviewTab} aria-current="page">
            运营总览
          </Link>
          <Link className="ops-tab" to={requestsTab}>
            问答诊断
          </Link>
          <Link className="ops-tab" to={documentsTab}>
            知识资产
          </Link>
        </nav>

        <section className="card ops-filter-card" aria-label="日期筛选">
          <div className="ops-filter-head">
            <div className="filter-row ops-filter-row">
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
              <span className="ops-custom-range">
                <label className="ops-date-label">
                  开始
                  <input
                    type="date"
                    className="filter-select"
                    value={sinceDraft}
                    max={untilDraft || today}
                    onChange={(event) => setSinceDraft(event.target.value)}
                  />
                </label>
                <label className="ops-date-label">
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
                  disabled={Boolean(customInvalid)}
                  onClick={() => updateFilters(applyWindow(filters, 'custom', { since: sinceDraft, until: untilDraft }))}
                >
                  应用
                </button>
              </span>
            ) : null}
          </div>
          <span className="ops-filter-meta">按问答结束时间归属 · Asia/Shanghai</span>
          </div>
          <p className="ops-window-note" data-testid="ops-window-label">
            {label}
            {filters.kind ? ` · 结果类型：${RESULT_LABELS[filters.kind as keyof typeof RESULT_LABELS] ?? filters.kind}` : ''}
          </p>
          {rangeInvalid ? (
            <p className="ops-inline-error" role="alert">
              {resolved.error}
            </p>
          ) : null}
        </section>

        {loading ? (
          <div className="ops-loading" data-testid="ops-loading" role="status">
            <span className="spinner spinner-sm" aria-hidden="true" />
            正在加载运营总览…
          </div>
        ) : null}

        {loadError && !loading ? (
          <div className="notice notice-error" role="alert" data-testid="ops-error">
            <Icon name="alert-circle" size={16} className="notice-icon" />
            <div className="notice-body">
              <p style={{ fontWeight: 600 }}>运营数据加载失败</p>
              <p style={{ marginTop: 4 }}>{loadError}</p>
              <div className="notice-actions">
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  data-testid="ops-retry"
                  onClick={() => setRetryKey((value) => value + 1)}
                >
                  重试
                </button>
              </div>
            </div>
          </div>
        ) : null}

        {data && !loading && !loadError ? (
          <div data-testid="ops-ready">
            <section className="ops-metrics" aria-label="核心指标">
              <button
                type="button"
                className="card ops-metric"
                data-testid="ops-metric-completed-card"
                onClick={() => goKind('')}
              >
                <span className="ops-metric-label">已完成问答</span>
                <span className="ops-metric-value" data-testid="ops-metric-completed">
                  {metrics?.completed_requests ?? 0}
                </span>
                <span className="ops-metric-hint">窗口内已完成请求，点击查看全部</span>
              </button>
              <button
                type="button"
                className="card ops-metric ops-metric-warn"
                data-testid="ops-metric-not-found-card"
                onClick={() => goKind('not_found')}
              >
                <span className="ops-metric-label">未找到</span>
                <span className="ops-metric-value" data-testid="ops-metric-not_found">
                  {metrics?.not_found ?? 0}
                </span>
                <span className="ops-metric-hint" data-testid="ops-not-found-share">
                  {shareText(metrics?.not_found ?? 0, metrics?.completed_requests ?? 0)}
                </span>
              </button>
              <button
                type="button"
                className="card ops-metric ops-metric-amber"
                data-testid="ops-metric-conflict-card"
                onClick={() => goKind('conflict')}
              >
                <span className="ops-metric-label">资料冲突</span>
                <span className="ops-metric-value" data-testid="ops-metric-conflict">
                  {metrics?.conflict ?? 0}
                </span>
                <span className="ops-metric-hint">需管理员核实</span>
              </button>
              <button
                type="button"
                className="card ops-metric"
                data-testid="ops-metric-review-card"
                onClick={() =>
                  navigate(
                    documentsPath({
                      ...filters,
                      kind: '',
                      documentId: '',
                      versionId: '',
                      state: 'review_required',
                    }),
                  )
                }
              >
                <span className="ops-metric-label">
                  待审核版本 <span className="badge badge-slate">当前</span>
                </span>
                <span className="ops-metric-value" data-testid="ops-metric-review_required_versions">
                  {metrics?.review_required_versions ?? 0}
                </span>
                <span className="ops-metric-hint">与日期筛选无关</span>
              </button>
            </section>

            <section className="ops-secondary" aria-label="其他运营状态">
              <div className="ops-secondary-item">
                <span className="ops-secondary-label">中断请求</span>
                <span className="ops-secondary-value" data-testid="ops-metric-interrupted">
                  {metrics?.interrupted ?? 0}
                </span>
                <span className="ops-secondary-note">单列统计，不计入结果分布</span>
              </div>
              <div className="ops-secondary-item">
                <span className="ops-secondary-label">
                  生效资料 <span className="badge badge-slate">当前</span>
                </span>
                <span className="ops-secondary-value" data-testid="ops-metric-active_documents">
                  {metrics?.active_documents ?? 0}
                </span>
                <span className="ops-secondary-note">库存口径，不随日期窗口回溯</span>
              </div>
              <div className="ops-secondary-item">
                <span className="ops-secondary-label">Trace 覆盖</span>
                <span className="ops-secondary-value" data-testid="ops-trace">
                  {traceStatusText(data.trace_coverage)}
                </span>
                <span className="ops-secondary-note">
                  {data.trace_coverage.note ?? '按记录状态展示，不换算为百分比'}
                </span>
              </div>
            </section>

            <div className="ops-charts">
              <section className="card" aria-label="问答趋势">
                <div className="card-header">
                  <h3 className="card-title">问答趋势</h3>
                  <span className="ops-chart-unit">单位：次</span>
                </div>
                <div className="card-body">
                  <p className="ops-chart-note" data-testid="ops-trend-hint">
                    点击任一天节点 → 该日问答明细
                  </p>
                  {trend.length > 0 ? (
                    <>
                      <EChart
                        option={trendOption(trend, animation)}
                        ariaLabel="问答趋势折线图，点击某天按该日期下钻"
                        testId="ops-chart-trend"
                        categoryCount={trend.length}
                        onCategoryClick={(index) => {
                          const point = trend[index];
                          if (point) goDay(point.date);
                        }}
                      />
                      <div className="ops-keyboard-list" role="group" aria-label="按日期下钻的键盘入口">
                        {trend.map((point) => (
                          <button
                            key={point.date}
                            type="button"
                            className="btn btn-ghost btn-sm"
                            data-trend-date={point.date}
                            onClick={() => goDay(point.date)}
                          >
                            {point.date} · 完成 {point.completed}
                          </button>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="empty-state ops-chart-empty" data-testid="ops-trend-empty">
                      <h4 className="empty-title">窗口内暂无完成问答</h4>
                      <p className="empty-desc">换一个日期窗口后再看趋势。</p>
                    </div>
                  )}
                </div>
              </section>

              <section className="card" aria-label="结果分布">
                <div className="card-header">
                  <h3 className="card-title">结果分布</h3>
                  <span className="ops-chart-unit">点击条形查看明细</span>
                </div>
                <div className="card-body">
                  <p className="ops-chart-note" data-testid="ops-dist-hint">
                    {`${distributionLead}共 ${distributionTotal} 条，${answeredText(distributionValues.answer ?? 0, distributionTotal)}`}
                  </p>
                  {distributionTotal > 0 ? (
                    <>
                      <EChart
                        option={distributionOption(distributionValues, animation)}
                        ariaLabel="结果分布横向条形图，点击某类按该类型下钻"
                        testId="ops-chart-distribution"
                        categoryCount={RESULT_KINDS.length}
                        categoryAxis="y"
                        onCategoryClick={(index) => {
                          const kind = RESULT_KINDS[index];
                          if (kind) goKind(kind);
                        }}
                      />
                      <div className="ops-keyboard-list" role="group" aria-label="按结果类型下钻的键盘入口">
                        {RESULT_KINDS.map((kind) => (
                          <button
                            key={kind}
                            type="button"
                            className="btn btn-ghost btn-sm"
                            data-kind={kind}
                            onClick={() => goKind(kind)}
                          >
                            {RESULT_LABELS[kind]} · {distributionValues[kind]}
                          </button>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="empty-state ops-chart-empty" data-testid="ops-dist-empty">
                      <h4 className="empty-title">窗口内暂无问答结果</h4>
                      <p className="empty-desc">结果分布会随完成问答自动出现。</p>
                    </div>
                  )}
                </div>
              </section>
            </div>

            <section className="card ops-pending-card" aria-label="待处理事项">
              <div className="card-header ops-pending-header">
                <div>
                  <h3 className="card-title">
                    待处理事项 <span className="ops-pending-count">{pending.length} 项</span>
                  </h3>
                  <p className="ops-card-sub">问答异常与资料处理</p>
                </div>
              </div>
              <div className="card-body">
                {pending.length === 0 ? (
                  <div className="empty-state" data-testid="ops-pending-empty">
                    <h4 className="empty-title">暂无待处理事项</h4>
                    <p className="empty-desc">异常问答与失败导入会出现在这里。</p>
                  </div>
                ) : (
                  <div className="ops-pending-table-wrap">
                    <table className="ops-pending-table">
                      <thead>
                        <tr>
                          <th scope="col">时间</th>
                          <th scope="col">异常类型</th>
                          <th scope="col">相关问题或文件</th>
                          <th scope="col">查看</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pending.map((item, index) =>
                          item.type === 'import' ? (
                            <tr key={`${item.type}-${item.version_id ?? index}`}>
                              <td className="ops-pending-time">{formatMoment(item.finished_at)}</td>
                              <td>
                                <span className="badge badge-rose">导入失败</span>
                              </td>
                              <td>
                                <span className="ops-pending-primary">
                                  资料导入 · {item.error_code ?? '未返回错误码'}
                                </span>
                                {item.document_id ? (
                                  <span className="ops-pending-secondary">文档 {shortId(item.document_id)}</span>
                                ) : null}
                              </td>
                              <td>
                                <button
                                  type="button"
                                  className="ops-table-action"
                                  data-pending-import
                                  data-state={item.state ?? ''}
                                  onClick={() => goImportPending(item)}
                                >
                                  查看资产 <Icon name="arrow-right" size={14} />
                                </button>
                              </td>
                            </tr>
                          ) : (
                            <tr key={`${item.type}-${item.request_id ?? index}`}>
                              <td className="ops-pending-time">{formatMoment(item.finished_at)}</td>
                              <td>
                                <span
                                  className={`badge ${item.kind === 'service_error' ? 'badge-rose' : 'badge-amber'}`}
                                >
                                  {pendingKindLabel(item)}
                                </span>
                              </td>
                              <td>
                                <span className="ops-pending-primary">
                                  {pendingKindLabel(item)}
                                  {item.error_code ? ` · ${item.error_code}` : ''}
                                </span>
                              </td>
                              <td>
                                <button
                                  type="button"
                                  className="ops-table-action"
                                  data-pending-request
                                  data-kind={item.kind ?? ''}
                                  onClick={() => goRequestPending(item)}
                                >
                                  查看诊断 <Icon name="arrow-right" size={14} />
                                </button>
                              </td>
                            </tr>
                          ),
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </section>
          </div>
        ) : null}

        {!data && !loading && !loadError ? (
          <div className="empty-state" data-testid="ops-empty">
            <h4 className="empty-title">暂无运营数据</h4>
            <p className="empty-desc">
              默认窗口为{WINDOW_LABELS[DEFAULT_WINDOW]}，最多回溯 {MAX_WINDOW_DAYS} 天。
            </p>
          </div>
        ) : null}

        <footer className="ops-footer">
          <span>本页为只读运营工作台 · 指标、图表与明细取自同一查询条件</span>
          {demoEnvironment ? <span className="ops-footer-env">演示环境 · 受控样本数据</span> : null}
        </footer>
      </div>
    </div>
  );
}
