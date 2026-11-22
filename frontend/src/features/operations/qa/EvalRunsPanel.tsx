/**
 * 固定评测页签：只读批次列表 + 单批次聚合摘要。
 * P3 不发起评测：无「开始评测 / 重试 / 报告下载」入口；holdout 只显示聚合徽章，不请求逐题。
 */
import { useEffect, useState } from 'react';
import { ApiError } from '../../../api/client';
import { Icon } from '../../../components/Icon';
import type { EvaluationRunItem, RunResponse } from './qaApi';
import { qaApi } from './qaApi';
import { degradedText, evalStatusOf, formatYmdHm, shortId } from './qaMeta';
import './qa.css';

const STATUS_NOTE: Record<string, string> = {
  ok: '已加载批次',
  empty: '未找到可用批次',
};

export function EvalRunsPanel() {
  const [runs, setRuns] = useState<EvaluationRunItem[] | null>(null);
  const [listStatus, setListStatus] = useState<'ok' | 'empty'>('empty');
  const [skipped, setSkipped] = useState(0);
  const [degraded, setDegraded] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const [openRunId, setOpenRunId] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    qaApi
      .listEvaluationRuns(controller.signal)
      .then((payload) => {
        setRuns(payload.runs ?? []);
        setListStatus(payload.status);
        setSkipped(payload.skipped ?? 0);
        setDegraded(payload.degraded_reason ?? null);
        setLoading(false);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setRuns(null);
        setLoading(false);
        if (caught instanceof ApiError && caught.status === 403) setError('当前账号无权查看评测批次。');
        else setError(caught instanceof Error ? caught.message : '评测批次读取失败');
      });
    return () => controller.abort();
  }, [retryKey]);

  return (
    <section aria-label="固定评测批次" data-testid="qa-eval-panel">
      <div className="qa-note-bar">
        固定评测使用一组固定问法回归验证回答质量；评测结果不影响线上问答，也不改变资料生效版本。
      </div>

      {loading ? (
        <p className="qa-loading" role="status" data-testid="qa-eval-loading">
          <span className="spinner spinner-sm" aria-hidden="true" /> 正在读取评测批次…
        </p>
      ) : error ? (
        <div className="notice notice-error" role="alert" data-testid="qa-eval-error">
          <Icon name="alert-circle" size={16} className="notice-icon" />
          <div className="notice-body">
            <p>{error}</p>
            <div className="notice-actions">
              <button
                type="button"
                className="btn btn-primary btn-sm"
                data-testid="qa-eval-retry"
                onClick={() => setRetryKey((value) => value + 1)}
              >
                重试
              </button>
            </div>
          </div>
        </div>
      ) : (runs ?? []).length === 0 ? (
        <div className="empty-state" data-testid="qa-eval-empty">
          <h4 className="empty-title">未找到可用批次</h4>
          <p className="empty-desc">
            {STATUS_NOTE[listStatus] ?? '评测目录内没有可读批次'}
            {skipped > 0 ? `；已跳过 ${skipped} 个空目录或无 manifest 目录` : ''}
            {degraded ? `；${degradedText(degraded)}` : ''}
          </p>
        </div>
      ) : (
        <>
          {degraded ? (
            <p className="qa-inline-note" data-testid="qa-eval-degraded">
              {degradedText(degraded)}
            </p>
          ) : null}
          <div className="qa-table-wrap">
            <table className="qa-table qa-eval-table" data-testid="qa-eval-table">
              <thead>
                <tr>
                  <th scope="col" className="qa-col-batch">
                    批次
                  </th>
                  <th scope="col" className="qa-col-samples">
                    样本数
                  </th>
                  <th scope="col" className="qa-col-status">
                    评测状态
                  </th>
                  <th scope="col" className="qa-col-time">
                    创建时间
                  </th>
                  <th scope="col" className="qa-col-action">
                    操作
                  </th>
                </tr>
              </thead>
              <tbody>
                {(runs ?? []).map((run) => {
                  const status = evalStatusOf(run);
                  const caseCount = run.manifest?.case_count ?? run.summary?.case_count ?? null;
                  return (
                    <tr key={run.run_id} data-run-id={run.run_id} data-eval-status={status.label}>
                      <td>
                        <p className="qa-batch-id">{run.run_id}</p>
                        <p className="qa-batch-sub">
                          {[run.manifest?.dataset_version ?? run.summary?.dataset_version, run.manifest?.suite ?? run.summary?.suite]
                            .filter(Boolean)
                            .join(' · ') || '数据集未记录'}
                        </p>
                        <p className="qa-batch-flags">
                          {run.holdout_detected ? <span className="qa-badge is-warn">holdout 批次</span> : null}
                          {run.details_withheld ? (
                            <span className="qa-badge is-muted" data-testid="qa-holdout-withheld">
                              holdout 明细已扣留，仅聚合可见
                            </span>
                          ) : null}
                          {run.degraded_reason ? <span className="qa-badge is-danger">{run.degraded_reason}</span> : null}
                        </p>
                      </td>
                      <td className="qa-cell-number" data-testid="qa-eval-case-count">
                        {caseCount === null ? '未记录' : caseCount}
                      </td>
                      <td>
                        <span className={`qa-eval-badge is-${status.tone}`} data-testid="qa-eval-status">
                          {status.label}
                        </span>
                        <p className="qa-eval-detail">{status.detail}</p>
                      </td>
                      <td className="qa-cell-time">{formatYmdHm(run.manifest?.created_at ?? null)}</td>
                      <td className="qa-cell-action">
                        <button
                          type="button"
                          className="qa-table-action"
                          data-view-run={run.run_id}
                          onClick={() => setOpenRunId(run.run_id)}
                        >
                          查看摘要 <Icon name="arrow-right" size={14} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="qa-section-foot">
            批次样本数保留接口原始分母；holdout 批次只提供聚合，逐题明细扣留。本页不发起评测。
          </p>
        </>
      )}

      {openRunId ? <EvalSummaryDrawer runId={openRunId} onClose={() => setOpenRunId(null)} /> : null}
    </section>
  );
}

function EvalSummaryDrawer({ runId, onClose }: { runId: string; onClose: () => void }) {
  const [data, setData] = useState<RunResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setData(null);
    qaApi
      .getEvaluationRun(runId, controller.signal)
      .then((payload) => {
        setData(payload);
        setLoading(false);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setLoading(false);
        if (caught instanceof ApiError && caught.status === 404) setError('该批次目录缺失或 manifest 不存在。');
        else setError(caught instanceof Error ? caught.message : '批次摘要读取失败');
      });
    return () => controller.abort();
  }, [runId, retryKey]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const manifest = data?.manifest ?? null;
  const summary = data?.summary ?? null;
  const gate = data?.gate ?? null;
  const metrics = Object.entries(summary?.metrics ?? {}).filter(([, value]) => typeof value === 'number');
  const statusCounts = Object.entries(summary?.status_counts ?? {});
  const gateStatuses = Object.entries(gate?.gate_status ?? {});

  return (
    <>
      <button type="button" className="scrim" aria-label="关闭批次摘要" onClick={onClose} />
      <aside className="drawer is-narrow qa-drawer" role="dialog" aria-modal="true" aria-label="批次摘要" data-testid="qa-eval-drawer">
        <header className="drawer-head">
          <div className="drawer-head-texts">
            <h2 className="drawer-title">批次摘要</h2>
            <p className="drawer-sub">只读聚合 · {shortId(runId)}</p>
          </div>
          <button type="button" className="qa-icon-btn" aria-label="关闭批次摘要" onClick={onClose} data-testid="qa-eval-drawer-close">
            <Icon name="x" size={18} />
          </button>
        </header>
        <div className="drawer-body">
          {loading ? (
            <p className="qa-loading" role="status">
              <span className="spinner spinner-sm" aria-hidden="true" /> 正在读取批次聚合…
            </p>
          ) : error ? (
            <div className="notice notice-error" role="alert" data-testid="qa-eval-drawer-error">
              <Icon name="alert-circle" size={16} className="notice-icon" />
              <div className="notice-body">
                <p>{error}</p>
                <div className="notice-actions">
                  <button type="button" className="btn btn-primary btn-sm" onClick={() => setRetryKey((value) => value + 1)}>
                    重试
                  </button>
                </div>
              </div>
            </div>
          ) : data ? (
            <>
              {data.details_withheld ? (
                <p className="qa-warn-bar" data-testid="qa-eval-drawer-withheld">
                  holdout 明细已扣留，仅聚合可见。
                </p>
              ) : null}
              {data.degraded_reason ? <p className="qa-inline-note">{degradedText(data.degraded_reason)}</p> : null}

              <section className="qa-section">
                <p className="qa-section-label">批次信息</p>
                <dl className="qa-meta-list">
                  <Row label="批次" value={data.run_id} />
                  <Row label="执行模式" value={manifest?.mode ?? summary?.mode ?? '未记录'} />
                  <Row label="范围" value={manifest?.scope ?? summary?.scope ?? '未记录'} />
                  <Row label="数据集" value={manifest?.suite ?? summary?.suite ?? '未记录'} />
                  <Row label="数据集版本" value={manifest?.dataset_version ?? summary?.dataset_version ?? '未记录'} />
                  <Row label="样本数（原始分母）" value={String(manifest?.case_count ?? summary?.case_count ?? '未记录')} />
                  <Row label="索引 revision" value={String(manifest?.index_revision ?? summary?.index_revision ?? '未记录')} />
                  <Row label="创建时间" value={formatYmdHm(manifest?.created_at ?? null)} />
                  <Row label="门禁版本" value={manifest?.gate_version ?? gate?.gate_version ?? '未记录'} />
                </dl>
              </section>

              {summary?.holdout ? (
                <section className="qa-section">
                  <p className="qa-section-label">holdout 聚合</p>
                  <dl className="qa-meta-list">
                    <Row label="仅提供聚合" value={summary.holdout.aggregate_only === false ? '否' : '是'} />
                    <Row label="是否写入明细" value={summary.holdout.details_written ? '是' : '否'} />
                    <Row label="标签版本" value={summary.holdout.label_version ?? '未记录'} />
                    <Row
                      label="元数据不一致"
                      value={String(summary.holdout.metadata_mismatch_count ?? '未记录')}
                    />
                  </dl>
                  {Object.entries(summary.holdout.strata ?? {}).length > 0 ? (
                    <div className="qa-kv-chips">
                      {Object.entries(summary.holdout.strata ?? {}).map(([key, value]) => (
                        <span className="qa-kv-chip" key={key}>
                          {key} <strong>{value}</strong>
                        </span>
                      ))}
                    </div>
                  ) : null}
                </section>
              ) : null}

              <section className="qa-section">
                <p className="qa-section-label">评测摘要</p>
                {summary ? (
                  <>
                    <dl className="qa-meta-list">
                      <Row label="已评分" value={String(summary.scored_count ?? '未记录')} />
                      <Row label="错误样本" value={String(summary.error_count ?? '未记录')} />
                      <Row label="跳过 OCR" value={String(summary.skipped_ocr_count ?? '未记录')} />
                    </dl>
                    {statusCounts.length > 0 ? (
                      <div className="qa-kv-chips">
                        {statusCounts.map(([key, value]) => (
                          <span className="qa-kv-chip" key={key}>
                            {key} <strong>{value}</strong>
                          </span>
                        ))}
                      </div>
                    ) : null}
                    <p className="qa-sub-label">批次指标（仅代表该批次受控执行结果）</p>
                    {metrics.length > 0 ? (
                      <dl className="qa-meta-list">
                        {metrics.map(([key, value]) => (
                          <Row key={key} label={key} value={String(value)} />
                        ))}
                      </dl>
                    ) : (
                      <p className="qa-empty-box">指标无样本</p>
                    )}
                  </>
                ) : (
                  <p className="qa-empty-box">该批次没有 summary，评测状态按缺失处理。</p>
                )}
              </section>

              <section className="qa-section">
                <p className="qa-section-label">门禁</p>
                {gate ? (
                  <>
                    <dl className="qa-meta-list">
                      <Row label="门禁状态" value={gate.quality_status ?? '未记录'} />
                      <Row label="失败项" value={String(gate.failure_count ?? 0)} />
                      <Row label="未知项" value={String(gate.unknown_count ?? 0)} />
                      <Row label="不适用" value={String(gate.not_applicable_count ?? 0)} />
                      <Row label="退出码" value={gate.exit_code === null || gate.exit_code === undefined ? '未记录' : String(gate.exit_code)} />
                    </dl>
                    {gateStatuses.length > 0 ? (
                      <div className="qa-kv-chips">
                        {gateStatuses.map(([key, value]) => (
                          <span className="qa-kv-chip" key={key}>
                            {key} <strong>{value}</strong>
                          </span>
                        ))}
                      </div>
                    ) : null}
                    {(gate.hard_failures ?? []).length > 0 ? (
                      <p className="qa-inline-note">硬失败项：{(gate.hard_failures ?? []).join('、')}</p>
                    ) : null}
                  </>
                ) : (
                  <p className="qa-empty-box">该批次没有 gate 结果，未做门禁判定。</p>
                )}
              </section>
            </>
          ) : null}
        </div>
        <footer className="drawer-foot">
          <div className="drawer-foot-row">
            <p className="drawer-foot-note">只读聚合；不提供逐题明细与报告下载</p>
            <button type="button" className="btn btn-secondary btn-sm" onClick={onClose}>
              关闭
            </button>
          </div>
        </footer>
      </aside>
    </>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="qa-meta-row">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
