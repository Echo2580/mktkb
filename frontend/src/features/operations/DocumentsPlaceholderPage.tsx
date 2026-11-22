import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ApiError } from '../../api/client';
import { useAuth } from '../../app/AuthProvider';
import { Icon } from '../../components/Icon';
import {
  WINDOW_KEYS,
  WINDOW_LABELS,
  applyWindow,
  documentsPath,
  mapDocumentState,
  overviewQuery,
  readFilters,
  requestsPath,
  resolveWindow,
  toSearch,
  toSearchParams,
  windowLabel,
  type OperationsFilters,
  type WindowKey,
} from './filters';
import './operations.css';
import './assets/assets.css';
import type { AssetDetail, DocumentItem } from './assets/assetsApi';
import { loadAllDocuments, loadDocumentDetail, loadDocumentDetails } from './assets/assetsApi';
import {
  FILE_TYPE_FILTERS,
  IMAGE_FILE_TYPES,
  STATE_FILTERS,
  describeNewVersion,
  describeNewVersionFallback,
  effectiveVersion,
  fileTypeMeta,
  formatMoment,
  latestVersion,
  needsDetail,
  newVersionToneClass,
  shortId,
} from './assets/assetModel';
import { AssetDrawer } from './assets/AssetDrawer';

const INITIAL_VISIBLE = 10;
const LOAD_MORE_STEP = 10;

function drawerErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return '该资料不存在或已删除，无法读取详情。';
    if (error.status === 403) return '当前账号无权读取运营数据。';
    return error.message;
  }
  return error instanceof Error ? error.message : '资料详情读取失败';
}

function listErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return '当前账号无权访问运营数据。';
    if (error.status === 422) return '筛选参数不合法，请重置筛选后重试。';
    return error.message;
  }
  return error instanceof Error ? error.message : '运营接口请求失败';
}

function mappedStateText(state: string): string {
  if (!state) return '';
  const mapping = mapDocumentState(state);
  const parts: string[] = [];
  if (mapping.versionState) parts.push(`version_state=${mapping.versionState}`);
  if (mapping.processingState) parts.push(`processing_state=${mapping.processingState}`);
  return parts.length > 0 ? `（${parts.join('，')}）` : '';
}

function shortWindowLabel(filters: OperationsFilters): string {
  if (filters.window === 'custom' || filters.since || filters.until) {
    return filters.since && filters.until ? `${filters.since} 至 ${filters.until}` : '自定义窗口';
  }
  return WINDOW_LABELS[filters.window];
}

export function OperationsDocumentsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => readFilters(searchParams), [searchParams]);
  const filterKey = toSearch(filters);
  const stateMapping = mapDocumentState(filters.state);
  const resolved = resolveWindow(filters);
  const rangeInvalid = Boolean(resolved.error);

  const [typeFilter, setTypeFilter] = useState('');
  const [nameInput, setNameInput] = useState('');
  const [bannerTouched, setBannerTouched] = useState(false);

  const [items, setItems] = useState<DocumentItem[]>([]);
  const [pages, setPages] = useState(0);
  const [truncated, setTruncated] = useState(false);
  const [detailMap, setDetailMap] = useState<Record<string, AssetDetail | null>>({});
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const detailCache = useRef<Map<string, AssetDetail>>(new Map());

  const [drawerDetail, setDrawerDetail] = useState<AssetDetail | null>(null);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [drawerError, setDrawerError] = useState<string | null>(null);

  const drawerId = filters.documentId;
  const apiFileType = typeFilter && typeFilter !== 'image' ? typeFilter : undefined;
  const nameQuery = nameInput.trim().toLowerCase();

  useEffect(() => {
    if (!isAdmin) return undefined;
    if (resolved.error) {
      setLoading(false);
      setLoadError(resolved.error);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setItems([]);
    setDetailMap({});
    setPages(0);
    setTruncated(false);
    setVisibleCount(INITIAL_VISIBLE);
    (async () => {
      try {
        const batch = await loadAllDocuments({
          ...overviewQuery(filters),
          fileType: apiFileType,
          versionState: stateMapping.versionState,
          processingState: stateMapping.processingState,
        });
        if (cancelled) return;
        const details = await loadDocumentDetails(batch.items.filter(needsDetail), detailCache.current);
        if (cancelled) return;
        const map: Record<string, AssetDetail | null> = {};
        details.forEach((value, key) => {
          map[key] = value;
        });
        setItems(batch.items);
        setPages(batch.pages);
        setTruncated(batch.truncated);
        setDetailMap(map);
        setLoading(false);
      } catch (caught) {
        if (cancelled) return;
        setItems([]);
        setDetailMap({});
        setLoading(false);
        setLoadError(listErrorMessage(caught));
      }
    })();
    return () => {
      cancelled = true;
    };
    // stateMapping 由 filters.state 派生；resolved.error 决定是否请求。
    // 详情补齐走只读详情端点，列表参数不含 document_id/version_id（T303 裁决 ②）。
  }, [filterKey, apiFileType, rangeInvalid, retryKey, isAdmin]);

  useEffect(() => {
    if (!isAdmin || !drawerId) {
      setDrawerDetail(null);
      setDrawerError(null);
      setDrawerLoading(false);
      return undefined;
    }
    const cached = detailCache.current.get(drawerId);
    if (cached) {
      setDrawerDetail(cached);
      setDrawerError(null);
      setDrawerLoading(false);
      return undefined;
    }
    let cancelled = false;
    setDrawerLoading(true);
    setDrawerError(null);
    loadDocumentDetail(drawerId)
      .then((detail) => {
        if (cancelled) return;
        detailCache.current.set(drawerId, detail);
        setDrawerDetail(detail);
        setDrawerLoading(false);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setDrawerDetail(null);
        setDrawerLoading(false);
        setDrawerError(drawerErrorMessage(caught));
      });
    return () => {
      cancelled = true;
    };
  }, [drawerId, isAdmin]);

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      if (typeFilter === 'image') {
        if (!IMAGE_FILE_TYPES.includes(item.file_type)) return false;
      } else if (typeFilter && item.file_type !== typeFilter) {
        return false;
      }
      if (nameQuery && !item.name.toLowerCase().includes(nameQuery)) return false;
      return true;
    });
  }, [items, typeFilter, nameQuery]);

  const total = filteredItems.length;
  const visibleItems = filteredItems.slice(0, visibleCount);
  const hasMore = visibleCount < total;
  const drawerItem = drawerId ? items.find((item) => item.document_id === drawerId) ?? null : null;

  const tabsSearch = toSearchParams(filters).toString();
  const overviewTab = `/operations?${tabsSearch}`;
  const requestsTab = `/operations/requests?${tabsSearch}`;
  const assetsTab = documentsPath(filters);

  const bannerVisible =
    filters.state === 'review_required' && !bannerTouched && !loading && !loadError && !rangeInvalid;

  function updateFilters(next: OperationsFilters) {
    setBannerTouched(true);
    setSearchParams(toSearchParams(next));
  }

  function resetFilters() {
    setBannerTouched(true);
    setTypeFilter('');
    setNameInput('');
    updateFilters({ ...filters, state: '', documentId: '', versionId: '' });
  }

  function openDocument(documentId: string) {
    setSearchParams(toSearchParams({ ...filters, documentId }));
  }

  function closeDrawer() {
    setSearchParams(toSearchParams({ ...filters, documentId: '' }));
  }

  function renderNewStatus(item: DocumentItem) {
    const detail = detailMap[item.document_id];
    if (detail === undefined) {
      const fallback = describeNewVersionFallback(item);
      if (fallback) {
        return (
          <span className={newVersionToneClass(fallback.tone)} data-testid="ops-asset-new" data-tone={fallback.tone}>
            {fallback.text}
          </span>
        );
      }
    }
    const latest = latestVersion(detail ?? null);
    const status = describeNewVersion(item, latest);
    return (
      <span
        className={newVersionToneClass(status.tone)}
        data-testid="ops-asset-new"
        data-tone={status.tone}
      >
        {status.text}
      </span>
    );
  }

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

  const effectiveForDrawer = effectiveVersion(drawerItem);
  const drawerActive = drawerDetail?.document.active_version_id
    ? (drawerDetail.versions ?? []).find((version) => version.version_id === drawerDetail.document.active_version_id) ?? null
    : null;
  const requestsFilter: OperationsFilters = {
    ...filters,
    kind: '',
    state: '',
    versionId: '',
    documentId: drawerId,
  };
  const versionRequestsFilter: OperationsFilters = {
    ...requestsFilter,
    versionId: drawerActive?.version_id ?? effectiveForDrawer?.version_id ?? '',
  };

  return (
    <div className="page-scroll">
      <div className="page page-admin">
        <div className="page-header">
          <div>
            <div className="asset-title-line">
              <h2 className="page-title">知识运营</h2>
              <span className="badge badge-slate">只读工作台</span>
            </div>
            <p className="page-desc">
              查看每份资料的生效版本、导入状态与被引用情况；处理失败版本请前往资料管理。
            </p>
          </div>
          <div className="page-actions">
            <Link className="btn btn-primary btn-sm" to="/documents">
              <Icon name="folder" size={15} />
              前往资料管理
            </Link>
          </div>
        </div>

        <nav className="ops-tabs" aria-label="运营工作台页面">
          <Link className="ops-tab" to={overviewTab}>
            运营总览
          </Link>
          <Link className="ops-tab" to={requestsTab}>
            问答诊断
          </Link>
          <Link className="ops-tab" to={assetsTab} aria-current="page">
            知识资产
          </Link>
        </nav>

        {bannerVisible ? (
          <div className="ops-assets-banner" role="status" data-testid="ops-review-banner">
            <Icon name="alert-triangle" size={16} className="ops-assets-banner-icon" />
            <div className="ops-assets-banner-body">
              <p className="ops-assets-banner-text">
                已按「当前待审核版本」筛选：
                <strong data-testid="ops-review-banner-count">{total}</strong>
                份资料存在待审核版本；已发布版本在审核通过前继续生效，无生效版本的资料暂不参与问答。
              </p>
              <div className="ops-assets-banner-actions">
                <button type="button" className="asset-inline-link" onClick={resetFilters}>
                  清除筛选
                </button>
                <span className="asset-muted">待审核为当前库存口径，不随日期窗口回溯。</span>
              </div>
            </div>
          </div>
        ) : null}

        <section className="card ops-assets-filters" aria-label="知识资产筛选">
          <div className="filter-row ops-filter-row" style={{ width: '100%' }}>
            <div className="asset-search">
              <Icon name="search" size={15} className="asset-search-icon" />
              <input
                type="search"
                className="asset-search-input"
                placeholder="搜索资料名称"
                aria-label="搜索资料名称"
                data-testid="ops-name-search"
                value={nameInput}
                onChange={(event) => {
                  setNameInput(event.target.value);
                  setBannerTouched(true);
                  setVisibleCount(INITIAL_VISIBLE);
                }}
              />
            </div>
            <label className="asset-filter-label" htmlFor="asset-type-filter">
              文件类型
            </label>
            <select
              id="asset-type-filter"
              className="asset-select"
              data-testid="ops-type-select"
              aria-label="文件类型"
              value={typeFilter}
              onChange={(event) => {
                setTypeFilter(event.target.value);
                setBannerTouched(true);
                setVisibleCount(INITIAL_VISIBLE);
              }}
            >
              {FILE_TYPE_FILTERS.map((option) => (
                <option key={option.value || 'all'} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <label className="asset-filter-label" htmlFor="asset-state-filter">
              处理状态
            </label>
            <select
              id="asset-state-filter"
              className="asset-select"
              data-testid="ops-state-select"
              aria-label="处理状态"
              value={filters.state}
              onChange={(event) => updateFilters({ ...filters, state: event.target.value })}
            >
              {STATE_FILTERS.map((option) => (
                <option key={option.value || 'all'} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <button type="button" className="btn btn-secondary btn-sm" data-testid="ops-reset" onClick={resetFilters}>
              重置
            </button>
            <span className="asset-total" data-testid="ops-filter-total">
              共 {total} 份资料
              <span className="ops-total-note" style={{ display: 'inline', marginLeft: 6 }}>
                （名称搜索为已加载页的客户端过滤）
              </span>
            </span>
          </div>
          <div className="asset-window-row">
            <span className="asset-filter-label">引用计数窗口</span>
            {(WINDOW_KEYS.filter((key) => key !== 'custom') as WindowKey[]).map((key) => (
              <button
                key={key}
                type="button"
                className={`btn btn-sm ${filters.window === key ? 'btn-primary' : 'btn-secondary'}`}
                aria-pressed={filters.window === key}
                data-asset-window={key}
                onClick={() => updateFilters(applyWindow(filters, key))}
              >
                {WINDOW_LABELS[key]}
              </button>
            ))}
            <span className="asset-window-note" data-testid="ops-window-label">
              {windowLabel(filters)}
            </span>
          </div>
          {rangeInvalid ? (
            <p className="ops-inline-error" role="alert">
              {resolved.error}
            </p>
          ) : null}
        </section>

        {loading ? (
          <div className="ops-loading" data-testid="ops-assets-loading" role="status">
            <span className="spinner spinner-sm" aria-hidden="true" />
            正在按游标累计知识资产…
          </div>
        ) : null}

        {loadError && !loading ? (
          <div className="notice notice-error" role="alert" data-testid="ops-assets-error">
            <Icon name="alert-circle" size={16} className="notice-icon" />
            <div className="notice-body">
              <p style={{ fontWeight: 600 }}>知识资产加载失败</p>
              <p style={{ marginTop: 4 }}>{loadError}</p>
              <div className="notice-actions">
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  data-testid="ops-assets-retry"
                  onClick={() => setRetryKey((value) => value + 1)}
                >
                  重试
                </button>
              </div>
            </div>
          </div>
        ) : null}

        {!loading && !loadError ? (
          <>
            <div className="ops-compat-bar" data-testid="ops-placeholder-ready">
              <span className="ops-compat-item">
                共 <strong data-testid="ops-placeholder-total">{total}</strong> 份资料
                <span className="asset-muted">
                  （按 next_cursor 累计 {pages} 页{truncated ? '，已达 20 页上限，总数可能不完整' : ''}）
                </span>
              </span>
              <span className="ops-compat-item">
                窗口{' '}
                <span className="ops-compat-value" data-testid="ops-placeholder-window">
                  {windowLabel(filters)}
                </span>
              </span>
              <span className="ops-compat-item">
                状态{' '}
                <span className="ops-compat-value" data-testid="ops-placeholder-state">
                  {filters.state || '全部'}
                  {mappedStateText(filters.state)}
                </span>
              </span>
              <span className="ops-compat-item">
                资料 ID{' '}
                <span className="ops-compat-value" data-testid="ops-placeholder-document">
                  {filters.documentId || '未指定'}
                </span>
              </span>
              {filters.versionId ? (
                <span className="ops-compat-item">
                  版本 ID <span className="ops-compat-value">{filters.versionId}</span>
                </span>
              ) : null}
            </div>

            <div className="asset-table-wrap">
              {total === 0 ? (
                <div className="asset-empty" data-testid="ops-assets-empty">
                  <Icon name="folder" size={26} className="asset-empty-icon" />
                  <p className="asset-empty-title">没有符合筛选条件的资料</p>
                  <button type="button" className="btn btn-secondary btn-sm asset-empty-action" onClick={resetFilters}>
                    清除筛选
                  </button>
                </div>
              ) : (
                <table className="asset-table" aria-label="知识资产列表">
                  <thead>
                    <tr>
                      <th scope="col" className="asset-col-name">资料名称</th>
                      <th scope="col" className="asset-col-type">类型</th>
                      <th scope="col" className="asset-col-current">当前生效版本</th>
                      <th scope="col" className="asset-col-new">新版处理状态</th>
                      <th scope="col" className="asset-col-ref">引用次数</th>
                      <th scope="col" className="asset-col-published">最近发布时间</th>
                      <th scope="col" className="asset-col-open">查看</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleItems.map((item) => {
                      const meta = fileTypeMeta(item.file_type);
                      const effective = effectiveVersion(item);
                      const selected = filters.documentId === item.document_id;
                      return (
                        <tr
                          key={item.document_id}
                          data-testid="ops-asset-row"
                          data-document-id={item.document_id}
                          data-name={item.name}
                          data-file-type={item.file_type}
                          data-selected={selected ? 'true' : 'false'}
                          tabIndex={0}
                          aria-label={`查看 ${item.name}`}
                          onClick={() => openDocument(item.document_id)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault();
                              openDocument(item.document_id);
                            }
                          }}
                        >
                          <td>
                            <div className="asset-name-cell">
                              <span className={`asset-name-tile ${meta.tile}`}>
                                <Icon name={meta.icon} size={16} />
                              </span>
                              <div className="asset-name-body">
                                <span className="asset-name" data-testid="ops-asset-name">
                                  {item.name}
                                </span>
                                <span className="asset-name-sub">资料 ID {shortId(item.document_id)}</span>
                              </div>
                            </div>
                          </td>
                          <td>
                            <span className="asset-type-text" data-testid="ops-asset-type">
                              {meta.label}
                            </span>
                          </td>
                          <td>
                            <span
                              className={`asset-version-badge ${effective ? 'is-effective' : 'is-none'}`}
                              data-testid="ops-asset-current"
                              data-current={effective ? 'effective' : 'none'}
                            >
                              {effective ? `V${effective.number} 生效` : '暂无生效版本'}
                            </span>
                          </td>
                          <td>{renderNewStatus(item)}</td>
                          <td className="asset-ref-count" data-testid="ops-asset-citations" title="最终引用（排除冲突问答）">
                            {item.final_citations}
                          </td>
                          <td className="asset-published" data-testid="ops-asset-published">
                            {formatMoment(effective?.published_at)}
                          </td>
                          <td className="asset-open-cell">
                            <button
                              type="button"
                              className="asset-open-button"
                              data-testid="ops-asset-open"
                              onClick={(event) => {
                                event.stopPropagation();
                                openDocument(item.document_id);
                              }}
                            >
                              详情
                              <Icon name="arrow-right" size={13} />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
              {total > 0 && hasMore ? (
                <div className="asset-load-more">
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    data-testid="ops-load-more"
                    onClick={() => setVisibleCount((value) => value + LOAD_MORE_STEP)}
                  >
                    加载更多
                  </button>
                  <span>
                    已显示 {visibleItems.length} / 共 {total} 份
                  </span>
                </div>
              ) : null}
            </div>

            <p className="asset-footer-notes">
              表脚口径：引用次数为所选窗口内最终引用（排除 kind='conflict' 的问答）；待审核与生效资料为当前库存口径，不随窗口回溯。
              名称搜索仅对已加载页做客户端过滤；处理后动作请前往资料管理。
            </p>
          </>
        ) : null}

        <footer className="ops-footer">
          <span>本页为只读运营工作台 · 资产列表与抽屉取自同一只读接口口径</span>
          <span>导入失败的版本不会参与问答，也不会替换当前生效版本</span>
        </footer>
      </div>

      {drawerId ? (
        <AssetDrawer
          documentId={drawerId}
          detail={drawerDetail}
          item={drawerItem}
          loading={drawerLoading}
          error={drawerError}
          windowLabelText={shortWindowLabel(filters)}
          requestsHref={requestsPath(requestsFilter)}
          versionRequestsHref={drawerActive ? requestsPath(versionRequestsFilter) : null}
          citation={{
            finalCitations: drawerItem ? drawerItem.final_citations : null,
            relatedRequests: drawerItem ? drawerItem.related_requests_count : null,
          }}
          onClose={closeDrawer}
        />
      ) : null}
    </div>
  );
}
