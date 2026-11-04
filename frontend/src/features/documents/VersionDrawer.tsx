import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, errorMessage, isApiError } from '../../api/client';
import type { DocumentDetail, JobStatus, PreviewResponse, VersionSummary } from '../../api/client';
import { ConfirmDialog, Drawer } from '../../components/Dialog';
import { Icon, fileIconFor } from '../../components/Icon';
import {
  JOB_STATE_LABELS,
  VERSION_STATE_LABELS,
  formatDateTime,
  jobTone,
  locatorParts,
  truncateMiddle,
  versionTone,
} from '../../utils/format';

interface VersionDrawerProps {
  documentId: string;
  initialVersionId?: string;
  jobRegistry: Record<string, string>;
  onClose: () => void;
  onChanged: (message: string, tone?: 'success' | 'error') => void;
  onJobKnown: (versionId: string, jobId: string) => void;
}

type ActionKind = 'publish' | 'cancel' | 'retry' | null;

function pickVersion(detail: DocumentDetail, preferred?: string): string | null {
  const versions = detail.versions;
  if (preferred && versions.some((version) => version.id === preferred)) return preferred;
  const latest = detail.document.latest_version;
  const active = detail.document.active_version;
  if (latest && active && latest.id !== active.id && ['review_required', 'failed', 'queued', 'processing'].includes(latest.state)) {
    return latest.id;
  }
  return latest?.id ?? active?.id ?? versions[versions.length - 1]?.id ?? null;
}

function ReportView({ report }: { report: Record<string, unknown> | null }) {
  if (!report) {
    return <p className="detail-section-hint">服务端尚未返回处理报告。</p>;
  }
  const quality = (report.quality ?? null) as { complete?: unknown; issues?: unknown } | null;
  const complete = typeof quality?.complete === 'boolean' ? quality.complete : null;
  const issues = Array.isArray(quality?.issues) ? quality.issues : [];
  const warnings = Array.isArray(report.warnings) ? report.warnings : [];
  const sheets = Array.isArray(report.sheets) ? (report.sheets as Array<Record<string, unknown>>) : [];
  const pages = Array.isArray(report.pages) ? (report.pages as Array<Record<string, unknown>>) : [];
  const kind = typeof report.kind === 'string' ? report.kind : null;

  return (
    <div className="report-box">
      <div className="report-head">
        <span>处理报告</span>
        {complete === null ? (
          <span className="badge badge-slate">未提供完整性结论</span>
        ) : complete ? (
          <span className="badge badge-emerald">处理完整</span>
        ) : (
          <span className="badge badge-rose">处理未完成</span>
        )}
      </div>
      <div className="report-body">
        {kind ? (
          <div className="report-row">
            <span className="report-key">解析类型</span>
            <span className="report-value">{kind}</span>
          </div>
        ) : null}
        {typeof report.units === 'number' ? (
          <div className="report-row">
            <span className="report-key">来源单元</span>
            <span className="report-value">{report.units}</span>
          </div>
        ) : null}
        {typeof report.total_pages === 'number' ? (
          <div className="report-row">
            <span className="report-key">总页数</span>
            <span className="report-value">{report.total_pages}</span>
          </div>
        ) : null}
        {typeof report.total_data_rows === 'number' ? (
          <div className="report-row">
            <span className="report-key">有效数据行</span>
            <span className="report-value">{report.total_data_rows}</span>
          </div>
        ) : null}
        {typeof report.hidden_sheet_count === 'number' ? (
          <div className="report-row">
            <span className="report-key">隐藏工作表</span>
            <span className="report-value">{report.hidden_sheet_count}</span>
          </div>
        ) : null}
        {typeof report.formula_cells === 'number' ? (
          <div className="report-row">
            <span className="report-key">公式单元格</span>
            <span className="report-value">{report.formula_cells}</span>
          </div>
        ) : null}
        {typeof report.paragraph_count === 'number' ? (
          <div className="report-row">
            <span className="report-key">段落</span>
            <span className="report-value">{report.paragraph_count}</span>
          </div>
        ) : null}
        {typeof report.table_count === 'number' ? (
          <div className="report-row">
            <span className="report-key">表格</span>
            <span className="report-value">{report.table_count}</span>
          </div>
        ) : null}
        {typeof report.embedded_images === 'number' ? (
          <div className="report-row">
            <span className="report-key">内嵌图片（未 OCR）</span>
            <span className="report-value">{report.embedded_images}</span>
          </div>
        ) : null}

        {issues.length > 0 ? (
          <div className="report-warning">
            <p style={{ fontWeight: 600 }}>质量问题</p>
            <ul style={{ margin: '4px 0 0', paddingLeft: 16 }}>
              {issues.map((issue, index) => (
                <li key={index}>{typeof issue === 'object' && issue !== null ? JSON.stringify(issue) : String(issue)}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {warnings.length > 0 ? (
          <div className="report-warning">
            <p style={{ fontWeight: 600 }}>解析提示</p>
            <ul style={{ margin: '4px 0 0', paddingLeft: 16 }}>
              {warnings.map((warning, index) => (
                <li key={index}>{typeof warning === 'object' && warning !== null ? JSON.stringify(warning) : String(warning)}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {sheets.length > 0 ? (
          <div style={{ marginTop: 8, overflowX: 'auto' }}>
            <table className="preview-table">
              <thead>
                <tr>
                  <th scope="col">工作表</th>
                  <th scope="col">隐藏</th>
                  <th scope="col">入库</th>
                  <th scope="col">表头行</th>
                  <th scope="col">数据行</th>
                  <th scope="col">说明</th>
                </tr>
              </thead>
              <tbody>
                {sheets.map((sheet, index) => (
                  <tr key={index}>
                    <td>{String(sheet.name ?? '')}</td>
                    <td>{sheet.hidden ? '是' : '否'}</td>
                    <td>{sheet.ingested ? '是' : '否'}</td>
                    <td>{sheet.header_row === null || sheet.header_row === undefined ? '—' : String(sheet.header_row)}</td>
                    <td>{String(sheet.data_rows ?? 0)}</td>
                    <td style={{ color: 'var(--slate-500)' }}>{String(sheet.note ?? '')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {pages.length > 0 ? (
          <div style={{ marginTop: 8, overflowX: 'auto' }}>
            <table className="preview-table">
              <thead>
                <tr>
                  <th scope="col">页码</th>
                  <th scope="col">状态</th>
                  <th scope="col">来源</th>
                  <th scope="col">单元</th>
                  <th scope="col">原因</th>
                </tr>
              </thead>
              <tbody>
                {pages.map((page, index) => (
                  <tr key={index} className={page.status === 'failed' ? 'is-focus' : undefined}>
                    <td>{String(page.page ?? index + 1)}</td>
                    <td>{String(page.status ?? '')}</td>
                    <td>{String(page.source ?? '')}</td>
                    <td>{String(page.units ?? 0)}</td>
                    <td style={{ color: page.status === 'failed' ? 'var(--rose-700)' : 'var(--slate-500)' }}>
                      {typeof page.reason === 'object' && page.reason !== null ? JSON.stringify(page.reason) : String(page.reason ?? '')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {!kind && sheets.length === 0 && pages.length === 0 ? (
          <div className="report-row">
            <span className="report-key">报告字段</span>
            <span className="report-value">{Object.keys(report).join('、') || '空报告'}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function VersionDrawer({ documentId, initialVersionId, jobRegistry, onClose, onChanged, onJobKnown }: VersionDrawerProps) {
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(initialVersionId ?? null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [sheet, setSheet] = useState('');
  const [job, setJob] = useState<JobStatus | null>(null);
  const [jobTick, setJobTick] = useState(0);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<ActionKind>(null);
  const [confirmPublish, setConfirmPublish] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);

  const selected: VersionSummary | null = useMemo(() => {
    if (!detail) return null;
    return detail.versions.find((version) => version.id === selectedId) ?? null;
  }, [detail, selectedId]);
  const serverJob = useMemo(() => {
    if (!detail || !selectedId) return null;
    return (detail.jobs ?? []).find((item) => item.version_id === selectedId) ?? null;
  }, [detail, selectedId]);
  const activeJob = job && selectedId && job.version_id === selectedId ? job : null;
  const displayJob = activeJob ?? serverJob;
  const cachedJobId = selectedId ? jobRegistry[selectedId] ?? null : null;
  const jobId = displayJob?.id ?? cachedJobId;

  const refreshDetail = useCallback(
    async (preferredId?: string) => {
      const data = await api.getDocument(documentId);
      setDetail(data);
      setSelectedId((current) => pickVersion(data, preferredId ?? current ?? initialVersionId));
      return data;
    },
    [documentId, initialVersionId],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    refreshDetail(initialVersionId)
      .catch((caught) => {
        if (!cancelled) setLoadError(errorMessage(caught));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshDetail, initialVersionId]);

  useEffect(() => {
    if (!selectedId) return;
    setOffset(0);
    setSheet('');
    setPreview(null);
    setPreviewError(null);
  }, [selectedId]);

  useEffect(() => {
    if (!selectedId || !selected) return;
    if (['queued', 'processing', 'cancelled', 'deleted'].includes(selected.state)) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    setPreviewLoading(true);
    setPreviewError(null);
    api
      .preview(documentId, selectedId, { offset, limit: 20, sheet: sheet || undefined })
      .then((data) => {
        if (!cancelled) setPreview(data);
      })
      .catch((caught) => {
        if (!cancelled) setPreviewError(errorMessage(caught));
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [documentId, offset, selectedId, selected?.state, sheet]);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }
    let cancelled = false;
    let timer: number | null = null;
    async function poll() {
      try {
        const data = await api.getJob(jobId as string);
        if (cancelled) return;
        setJob(data);
        if (['succeeded', 'failed', 'blocked', 'cancelled'].includes(data.state)) {
          await refreshDetail(selectedId ?? undefined).catch(() => undefined);
        }
        if (['queued', 'running'].includes(data.state)) {
          timer = window.setTimeout(poll, 1500);
        }
      } catch {
        if (!cancelled) setJob(null);
      }
    }
    void poll();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [jobId, jobTick, refreshDetail, selectedId]);

  useEffect(() => {
    if (!selected || !['queued', 'processing'].includes(selected.state)) return;
    const timer = window.setInterval(() => {
      void refreshDetail(selectedId ?? undefined).catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [refreshDetail, selected, selectedId]);

  async function publish() {
    if (!detail || !selected) return;
    setActionBusy('publish');
    setActionError(null);
    try {
      await api.publish(documentId, selected.id, {
        expected_active_version_id: detail.document.active_version?.id ?? null,
        expected_revision: detail.revision,
      });
      setConfirmPublish(false);
      await refreshDetail(selected.id);
      onChanged(`V${selected.number} 已发布并生效`);
    } catch (caught) {
      setActionError(
        isApiError(caught) && (caught.code === 'PUBLISH_CONFLICT' || caught.code === 'VERSION_NOT_PUBLISHABLE')
          ? `${caught.message}；已重新读取当前版本状态，请核对后重试。`
          : errorMessage(caught),
      );
      await refreshDetail(selected.id).catch(() => undefined);
    } finally {
      setActionBusy(null);
    }
  }

  async function cancelVersion() {
    if (!selected) return;
    setActionBusy('cancel');
    setActionError(null);
    try {
      await api.cancelVersion(documentId, selected.id);
      setConfirmCancel(false);
      await refreshDetail(selected.id);
      onChanged(`V${selected.number} 已取消，旧有效版本保持不变`);
    } catch (caught) {
      setActionError(errorMessage(caught));
    } finally {
      setActionBusy(null);
    }
  }

  async function retryJob() {
    if (!jobId || !selected || !retryAvailable) return;
    setActionBusy('retry');
    setActionError(null);
    try {
      const updated = await api.retryJob(jobId);
      onJobKnown(selected.id, updated.id);
      setJob(updated);
      setJobTick((value) => value + 1);
      onChanged(`V${selected.number} 已重新排队处理`);
    } catch (caught) {
      setActionError(errorMessage(caught));
    } finally {
      setActionBusy(null);
    }
  }

  const fileMeta = fileIconFor(detail?.document.name ?? '文件');
  const report = preview?.report ?? (selected?.processing_report as Record<string, unknown> | null) ?? null;
  const sheetOptions = Array.isArray(report?.sheets)
    ? (report.sheets as Array<Record<string, unknown>>)
        .map((item) => (typeof item.name === 'string' ? item.name : null))
        .filter((name): name is string => Boolean(name))
    : [];
  const pageCount = preview ? Math.max(1, Math.ceil(preview.total / preview.limit)) : 1;
  const pageIndex = preview ? Math.floor(preview.offset / preview.limit) + 1 : 1;
  const retryAvailable =
    selected?.state === 'failed' &&
    displayJob?.retryable === true &&
    ['failed', 'blocked'].includes(displayJob.state);

  return (
    <>
      <Drawer
        title={selected?.state === 'review_required' ? '检查待确认版本' : '查看 / 检查'}
        subtitle={detail ? `${detail.document.name} · V${selected?.number ?? '—'}` : '正在读取资料…'}
        onClose={onClose}
        closeLabel="关闭检查抽屉"
        icon={
          <span className={`tile ${selected ? (selected.state === 'review_required' ? 'tile-amber' : fileMeta.tile) : fileMeta.tile}`}>
            <Icon name={selected?.state === 'review_required' ? 'clipboard-check' : fileMeta.icon} size={16} />
          </span>
        }
        tabs={
          detail && detail.versions.length > 0 ? (
            <div className="drawer-tabs" role="tablist" aria-label="资料版本">
              {detail.versions.map((version) => (
                <button
                  key={version.id}
                  type="button"
                  role="tab"
                  aria-selected={version.id === selectedId}
                  className="drawer-tab"
                  onClick={() => setSelectedId(version.id)}
                >
                  V{version.number} · {VERSION_STATE_LABELS[version.state] ?? version.state}
                </button>
              ))}
            </div>
          ) : undefined
        }
        footer={
          <div>
            {actionError ? (
              <div className="form-error" role="alert" style={{ marginBottom: 10 }}>
                <Icon name="alert-circle" size={14} className="notice-icon" />
                <span>{actionError}</span>
              </div>
            ) : null}
            <div className="drawer-foot-row">
              <p className="drawer-foot-note">
                {selected?.state === 'review_required'
                  ? `发布需版本待确认且处理完整；当前知识库版本 ${detail?.revision ?? '—'}`
                  : selected?.state === 'failed'
                    ? displayJob
                      ? ['failed', 'blocked'].includes(displayJob.state)
                        ? displayJob.retryable
                          ? '失败任务可重试，已保存的检查点会复用。'
                          : `该错误不可自动重试（${displayJob.error_code ?? '未知错误'}）；可取消版本后重新上传。`
                        : `任务状态：${JOB_STATE_LABELS[displayJob.state] ?? displayJob.state}。`
                      : jobId
                        ? '正在读取服务端任务状态…'
                        : '服务端未返回该版本的任务记录；可取消版本后重新上传。'
                    : '内容检查为只读；发布与取消会改变有效版本。'}
              </p>
              <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
                {selected && ['review_required', 'failed'].includes(selected.state) ? (
                  <button
                    type="button"
                    className="btn btn-secondary btn-md"
                    onClick={() => setConfirmCancel(true)}
                    disabled={actionBusy !== null}
                  >
                    取消版本
                  </button>
                ) : null}
                {retryAvailable ? (
                  <button type="button" className="btn btn-secondary btn-md" onClick={() => void retryJob()} disabled={actionBusy !== null}>
                    {actionBusy === 'retry' ? <span className="spinner spinner-sm" aria-hidden="true" /> : <Icon name="refresh-cw" size={13} />}
                    重试处理
                  </button>
                ) : null}
                {selected?.state === 'review_required' ? (
                  <button
                    type="button"
                    className="btn btn-primary btn-md"
                    onClick={() => setConfirmPublish(true)}
                    disabled={actionBusy !== null}
                  >
                    <Icon name="send" size={13} />
                    确认并发布
                  </button>
                ) : null}
                {!selected || !['review_required', 'failed'].includes(selected.state) ? (
                  <button type="button" className="btn btn-secondary btn-md" onClick={onClose}>
                    关闭
                  </button>
                ) : null}
              </div>
            </div>
          </div>
        }
      >
        {loading ? (
          <div className="empty-state">
            <span className="spinner" aria-hidden="true" />
            <p className="empty-desc" style={{ marginTop: 10 }}>
              正在读取资料与版本…
            </p>
          </div>
        ) : loadError ? (
          <div className="notice notice-error" role="alert">
            <Icon name="alert-circle" size={15} className="notice-icon" />
            <div className="notice-body">
              <p>{loadError}</p>
              <div className="notice-actions">
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => void refreshDetail().catch(() => undefined)}>
                  重试
                </button>
              </div>
            </div>
          </div>
        ) : !detail || !selected ? (
          <div className="empty-state">
            <span className="empty-icon">
              <Icon name="file-warning" size={20} />
            </span>
            <p className="empty-title">没有可显示的版本</p>
          </div>
        ) : (
          <div>
            <div className="detail-grid">
              <div className="detail-cell">
                <p className="detail-label">当前版本</p>
                <p className="detail-value">V{selected.number}</p>
              </div>
              <div className="detail-cell">
                <p className="detail-label">状态</p>
                <p className="detail-value">
                  <span className={`badge badge-${versionTone(selected.state)}`}>
                    {VERSION_STATE_LABELS[selected.state] ?? selected.state}
                  </span>
                </p>
              </div>
              <div className="detail-cell">
                <p className="detail-label">上传时间</p>
                <p className="detail-value">{formatDateTime(selected.uploaded_at)}</p>
              </div>
              <div className="detail-cell">
                <p className="detail-label">生效时间</p>
                <p className="detail-value">{formatDateTime(selected.published_at)}</p>
              </div>
              <div className="detail-cell" style={{ gridColumn: '1 / -1' }}>
                <p className="detail-label">文件 SHA-256</p>
                <p className="detail-value mono" title={selected.sha256}>
                  {truncateMiddle(selected.sha256, 12, 10)}
                </p>
              </div>
            </div>

            {displayJob ? (
              <div className="detail-section">
                <p className="detail-section-title">
                  <Icon name="loader-circle" size={13} />
                  处理任务
                </p>
                <div className="report-box" style={{ marginTop: 8 }}>
                  <div className="report-head">
                    <span>任务 {displayJob.id.slice(0, 8)}</span>
                    <span className={`badge badge-${jobTone(displayJob.state)}`}>
                      {JOB_STATE_LABELS[displayJob.state] ?? displayJob.state}
                    </span>
                  </div>
                  <div className="report-body">
                    <div className="report-row">
                      <span className="report-key">阶段</span>
                      <span className="report-value">{displayJob.stage || '—'}</span>
                    </div>
                    <div className="report-row">
                      <span className="report-key">进度</span>
                      <span className="report-value">
                        {displayJob.completed_pages} / {displayJob.total_pages || '—'}
                      </span>
                    </div>
                    {displayJob.error_code ? (
                      <div className="report-row">
                        <span className="report-key">错误码</span>
                        <span className="report-value" style={{ color: 'var(--rose-700)' }}>
                          {displayJob.error_code}
                        </span>
                      </div>
                    ) : null}
                    {displayJob.message ? (
                      <div className="report-row">
                        <span className="report-key">说明</span>
                        <span className="report-value">{displayJob.message}</span>
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            ) : null}

            {['queued', 'processing'].includes(selected.state) ? (
              <div className="notice notice-info" style={{ marginTop: 16 }} role="status">
                <span className="spinner" aria-hidden="true" />
                <div className="notice-body">
                  <p>{selected.state === 'queued' ? '任务已排队，等待后台 worker 领取。' : '正在提取内容，完成后状态变为待确认。'}</p>
                  <p style={{ marginTop: 2, fontSize: 11 }}>处理期间该版本不会参与问答；旧有效版本保持不变。面板会自动刷新状态。</p>
                </div>
              </div>
            ) : null}

            {selected.state === 'cancelled' || selected.state === 'deleted' ? (
              <div className="notice notice-error" style={{ marginTop: 16 }}>
                <Icon name="ban" size={15} className="notice-icon" />
                <div className="notice-body">
                  <p>该版本已{selected.state === 'cancelled' ? '取消' : '删除'}，提取内容与原件不可访问。</p>
                </div>
              </div>
            ) : null}

            {['review_required', 'failed', 'published', 'superseded'].includes(selected.state) ? (
              <div className="detail-section">
                <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                  <p className="detail-section-title">
                    <Icon name="scan-eye" size={13} />
                    提取内容检查
                  </p>
                  {preview ? (
                    <span className="detail-section-hint">
                      共 {preview.total} 条来源单元 · 第 {pageIndex} / {pageCount} 页
                    </span>
                  ) : null}
                </div>
                {sheetOptions.length > 0 ? (
                  <select
                    className="filter-select"
                    style={{ marginTop: 8 }}
                    aria-label="按工作表筛选"
                    value={sheet}
                    onChange={(event) => {
                      setSheet(event.target.value);
                      setOffset(0);
                    }}
                  >
                    <option value="">全部工作表</option>
                    {sheetOptions.map((name) => (
                      <option key={name} value={name}>
                        工作表：{name}
                      </option>
                    ))}
                  </select>
                ) : null}

                <ReportView report={report} />

                {previewLoading ? (
                  <div className="empty-state" style={{ padding: '20px 0' }} role="status">
                    <span className="spinner" aria-hidden="true" />
                    <p className="empty-desc" style={{ marginTop: 8 }}>
                      正在读取提取内容…
                    </p>
                  </div>
                ) : previewError ? (
                  <div className="form-error" role="alert" style={{ marginTop: 12 }}>
                    <Icon name="alert-circle" size={14} className="notice-icon" />
                    <span>{previewError}</span>
                  </div>
                ) : preview && preview.items.length > 0 ? (
                  <div style={{ marginTop: 12 }}>
                    {preview.items.map((unit) => {
                      const parts = locatorParts(unit.locator);
                      return (
                        <div className="preview-unit" key={unit.id}>
                          <div className="preview-unit-head">
                            <span className="badge badge-slate">{unit.kind}</span>
                            {parts.map((part) => (
                              <span className="locator-chip" key={part.key}>
                                {part.label} {part.value}
                              </span>
                            ))}
                          </div>
                          {unit.fields && Object.keys(unit.fields).length > 0 ? (
                            <div className="kv-grid">
                              {Object.entries(unit.fields).map(([key, value]) => (
                                <div className="kv-item" key={key}>
                                  <span className="kv-key">{key}</span>
                                  <span className="kv-value">
                                    {typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value)}
                                  </span>
                                </div>
                              ))}
                            </div>
                          ) : null}
                          {unit.text ? <p className="preview-unit-text">{unit.text}</p> : null}
                          {unit.warnings.length > 0 ? (
                            <p className="report-warning">提示：{unit.warnings.join('；')}</p>
                          ) : null}
                        </div>
                      );
                    })}
                    <div className="pager">
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        disabled={preview.offset <= 0}
                        onClick={() => setOffset(Math.max(0, preview.offset - preview.limit))}
                      >
                        <Icon name="chevron-left" size={13} />
                        上一页
                      </button>
                      <span className="page-info">
                        {preview.offset + 1}–{Math.min(preview.offset + preview.limit, preview.total)} / {preview.total}
                      </span>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        disabled={preview.offset + preview.limit >= preview.total}
                        onClick={() => setOffset(preview.offset + preview.limit)}
                      >
                        下一页
                        <Icon name="chevron-right" size={13} />
                      </button>
                    </div>
                  </div>
                ) : (
                  <p className="detail-section-hint" style={{ marginTop: 12 }}>
                    该版本没有可展示的来源单元{preview ? `（共 ${preview.total} 条）` : ''}。
                  </p>
                )}
              </div>
            ) : null}
          </div>
        )}
      </Drawer>

      {confirmPublish && selected ? (
        <ConfirmDialog
          title={`确认发布 V${selected.number}？`}
          description={`发布后该版本立即成为「${detail?.document.name ?? '该资料'}」的有效版本，员工问答开始使用新内容；旧有效版本转为已被替换。`}
          confirmLabel="确认发布"
          tone="default"
          busy={actionBusy === 'publish'}
          onConfirm={() => void publish()}
          onCancel={() => setConfirmPublish(false)}
        />
      ) : null}

      {confirmCancel && selected ? (
        <ConfirmDialog
          title={`取消 V${selected.number}？`}
          description="仅取消该未生效版本及其任务，旧有效版本保持不变。取消后该版本的提取内容与原件不可访问。"
          confirmLabel="取消版本"
          busy={actionBusy === 'cancel'}
          onConfirm={() => void cancelVersion()}
          onCancel={() => setConfirmCancel(false)}
        />
      ) : null}
    </>
  );
}
