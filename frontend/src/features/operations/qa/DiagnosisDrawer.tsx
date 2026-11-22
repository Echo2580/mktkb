/**
 * 问答诊断抽屉（右侧 520px，Esc / 遮罩关闭）。
 * 只渲染服务端已关联的只读字段：问题、结果、revision、引用、冲突两方、执行阶段。
 * 不提供「打开会话记录」入口（跨用户会话归属校验不变）。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '../../../api/client';
import { Icon } from '../../../components/Icon';
import { AttemptList } from './StageBars';
import type { RequestDetailResponse } from './qaApi';
import { qaApi } from './qaApi';
import {
  citationState,
  formatMoment,
  kindMeta,
  locatorText,
  shortId,
} from './qaMeta';
import './qa.css';

interface Props {
  requestId: string;
  /** 列表条目上的完成时间（详情接口不返回该字段，缺失时明确显示未记录）。 */
  finishedAt?: string | null;
  onClose: () => void;
}

const TRACE_STATE: Record<string, { title: string; note: string }> = {
  disabled: {
    title: 'Trace 已关闭',
    note: '该环境未开启执行记录；问答内容与引用资料仍可正常查看。',
  },
  unavailable: {
    title: 'Trace 暂不可用',
    note: '执行记录读取失败，未展示阶段与耗时；问答内容与引用资料仍可正常查看。',
  },
  not_recorded: {
    title: '本次未记录执行过程',
    note: '请求没有关联的执行记录（可能早退或未记录）；问答内容与引用资料仍可正常查看。',
  },
};

export function DiagnosisDrawer({ requestId, finishedAt, onClose }: Props) {
  const [detail, setDetail] = useState<RequestDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const closeRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setDetail(null);
    qaApi
      .getRequestDetail(requestId, controller.signal)
      .then((payload) => {
        setDetail(payload);
        setLoading(false);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setLoading(false);
        if (caught instanceof ApiError) {
          if (caught.status === 404) setError('该记录不存在，或所属会话已被删除。');
          else if (caught.status === 403) setError('当前账号无权查看该诊断记录。');
          else setError(caught.message || '诊断详情读取失败');
        } else {
          setError(caught instanceof Error ? caught.message : '诊断详情读取失败');
        }
      });
    return () => controller.abort();
  }, [requestId, retryKey]);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
      }
    },
    [onClose],
  );

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  const meta = kindMeta(detail?.result.kind);
  const citations = detail?.citations ?? [];
  const conflicts = detail?.conflicts ?? [];
  const attempts = detail?.trace.attempts ?? [];
  const traceStatus = detail?.trace.status ?? 'not_recorded';
  const traceState = TRACE_STATE[traceStatus];
  const answerText = (detail?.result.text ?? '').trim();

  return (
    <>
      <button type="button" className="scrim" aria-label="关闭问答诊断" onClick={onClose} />
      <aside className="drawer qa-drawer" role="dialog" aria-modal="true" aria-labelledby="qa-drawer-title" data-testid="qa-drawer">
        <header className="drawer-head">
          <div className="drawer-head-texts">
            <h2 className="drawer-title" id="qa-drawer-title">
              问答诊断
            </h2>
            <p className="drawer-sub">只读记录 · 请求 {shortId(requestId)}</p>
          </div>
          <button
            type="button"
            className="qa-icon-btn"
            aria-label="关闭抽屉"
            data-testid="qa-drawer-close"
            onClick={onClose}
            ref={closeRef}
          >
            <Icon name="x" size={18} />
          </button>
        </header>

        <div className="drawer-body">
          {loading ? (
            <p className="qa-loading" role="status" data-testid="qa-detail-loading">
              <span className="spinner spinner-sm" aria-hidden="true" /> 正在读取诊断详情…
            </p>
          ) : error ? (
            <div className="notice notice-error" role="alert" data-testid="qa-detail-error">
              <Icon name="alert-circle" size={16} className="notice-icon" />
              <div className="notice-body">
                <p>{error}</p>
                <div className="notice-actions">
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    data-testid="qa-detail-retry"
                    onClick={() => setRetryKey((value) => value + 1)}
                  >
                    重试
                  </button>
                </div>
              </div>
            </div>
          ) : detail ? (
            <>
              <section className="qa-section">
                <p className="qa-section-label">原问题</p>
                <p className="qa-question" data-testid="qa-question">
                  {detail.question || '问题未记录'}
                </p>
                <p className="qa-question-meta" data-testid="qa-question-meta">
                  完成时间 {finishedAt ? formatMoment(finishedAt) : '未记录（列表未返回该记录）'}
                  {' · '}请求标识 {shortId(detail.request_id)}
                  {' · '}会话标识 {detail.conversation_id_hash}
                </p>
              </section>

              <section className="qa-result-card">
                <div className="qa-result-head">
                  <p className="qa-section-label">最终结果</p>
                  <span className={`qa-badge is-${meta.tone}`} data-testid="qa-result-badge">
                    {meta.label}
                  </span>
                </div>
                <p className="qa-result-note">{meta.note}</p>
                {answerText ? (
                  <div className="qa-answer-wrap">
                    <p className="qa-answer-label">回答内容</p>
                    <p className="qa-answer" data-testid="qa-answer">
                      {answerText}
                    </p>
                  </div>
                ) : null}
                <dl className="qa-meta-list">
                  <div className="qa-meta-row">
                    <dt>知识库 revision</dt>
                    <dd data-testid="qa-revision">
                      {detail.result.revision === null || detail.result.revision === undefined
                        ? '未记录'
                        : detail.result.revision}
                    </dd>
                  </div>
                  {detail.result.error_code ? (
                    <div className="qa-meta-row">
                      <dt>错误码</dt>
                      <dd data-testid="qa-error-code">{detail.result.error_code}</dd>
                    </div>
                  ) : null}
                  {detail.result.missing_fields && detail.result.missing_fields.length > 0 ? (
                    <div className="qa-meta-row">
                      <dt>待补充条件</dt>
                      <dd>{detail.result.missing_fields.join('、')}</dd>
                    </div>
                  ) : null}
                </dl>
              </section>

              {conflicts.length > 0 ? (
                <section className="qa-section" data-testid="qa-conflicts">
                  <div className="qa-section-head">
                    <p className="qa-section-label">冲突来源（两方均为当前有效版本）</p>
                  </div>
                  <div className="qa-conflict-notice">
                    两份资料均为当前有效版本，记载不一致，系统未自动判定哪一份正确。
                  </div>
                  {conflicts.map((group, groupIndex) => (
                    <div className="qa-conflict-group" key={`${group.field}-${groupIndex}`}>
                      <p className="qa-conflict-field">冲突字段：{group.field || '未记录'}</p>
                      <div className="qa-conflict-grid">
                        {(group.entries ?? []).map((entry, entryIndex) => {
                          const state = citationState(entry.status);
                          return (
                            <article
                              className="qa-conflict-card"
                              key={`${entry.source_id}-${entryIndex}`}
                              data-conflict-entry={entry.source_id}
                              data-status={state.tone}
                            >
                              <p className="qa-ref-name">{entry.document_name ?? `文档 ${shortId(entry.document_id)}`}</p>
                              <p className="qa-ref-sub">
                                {entry.version_number ? `V${entry.version_number}` : '版本未记录'}
                                <span className={`qa-state is-${state.tone}`}>{state.label}</span>
                              </p>
                              <p className="qa-conflict-value">{entry.value || '值未记录'}</p>
                              <p className="qa-ref-foot">来源单元 {shortId(entry.source_id)}</p>
                            </article>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                  {(conflicts[0]?.entries ?? []).length < 2 ? (
                    <p className="qa-explain">接口仅返回 {conflicts[0]?.entries?.length ?? 0} 个来源，未补齐另一方。</p>
                  ) : null}
                  <p className="qa-suggest">
                    <Icon name="info" size={14} /> 建议处理：前往资料管理核对两份资料，更新或作废旧版本后重新发布。
                  </p>
                  <Link className="qa-inline-link" to="/documents">
                    前往资料管理 <Icon name="arrow-right" size={14} />
                  </Link>
                </section>
              ) : null}

              {detail.result.kind === 'conflict' && conflicts.length === 0 ? (
                <section className="qa-section" data-testid="qa-conflicts-empty">
                  <div className="qa-section-head">
                    <p className="qa-section-label">冲突来源</p>
                  </div>
                  <p className="qa-empty-box">该冲突记录未返回两方来源，不补造来源卡片。</p>
                </section>
              ) : null}

              {detail.result.kind !== 'conflict' ? (
                <section className="qa-section" data-testid="qa-citations">
                  <div className="qa-section-head">
                    <p className="qa-section-label">引用资料及版本</p>
                    <Link className="qa-inline-link" to="/documents">
                      资料管理 <Icon name="arrow-right" size={14} />
                    </Link>
                  </div>
                  {citations.length === 0 ? (
                    <p className="qa-empty-box" data-testid="qa-no-citations">
                      本次回答未引用资料
                    </p>
                  ) : (
                    <div className="qa-ref-list">
                      {citations.map((citation) => {
                        const state = citationState(citation.status);
                        const locator = state.tone === 'active' ? locatorText(citation.locator) : '';
                        return (
                          <article
                            className="qa-ref-card"
                            key={citation.source_id}
                            data-citation={citation.document_id}
                            data-source-id={citation.source_id}
                            data-status={state.tone}
                          >
                            <div className="qa-ref-title">
                              <p className="qa-ref-name">
                                {citation.document_name ?? `文档 ${shortId(citation.document_id)}`}
                              </p>
                              <span className="qa-ref-version">
                                {citation.version_number ? `V${citation.version_number}` : '版本未记录'}
                              </span>
                            </div>
                            <p className="qa-ref-sub">
                              <span className={`qa-state is-${state.tone}`}>{state.label}</span>
                              {citation.published_at ? ` · 生效 ${formatMoment(citation.published_at)}` : ' · 生效时间未记录'}
                            </p>
                            {state.tone === 'active' ? (
                              <p className="qa-ref-locator">
                                {locator ? `定位：${locator}` : '定位未记录'}
                              </p>
                            ) : (
                              <p className="qa-ref-locator is-muted">该版本已失效，仅展示元信息，不提供正文与定位。</p>
                            )}
                          </article>
                        );
                      })}
                    </div>
                  )}
                  <p className="qa-section-foot">本回答最终引用 {detail.citation_count} 份资料（按文档去重，冲突来源不计入）。</p>
                </section>
              ) : null}

              <section className="qa-section" data-testid="qa-trace-section">
                <div className="qa-section-head">
                  <p className="qa-section-label">执行阶段</p>
                  {attempts.length > 0 ? <span className="qa-count-chip">{attempts.length} 次执行尝试</span> : null}
                </div>
                {attempts.length > 0 ? (
                  <AttemptList attempts={attempts} />
                ) : traceState ? (
                  <div className="qa-trace-state" data-testid="qa-trace-state" data-status={traceStatus}>
                    <p className="qa-trace-title">
                      <Icon name="info" size={15} /> {traceState.title}
                    </p>
                    <p className="qa-trace-note">{traceState.note}</p>
                  </div>
                ) : null}
                {attempts.length > 0 ? (
                  <p className="qa-section-foot">仅展示实际记录的阶段与耗时；未记录阶段不补 0，不显示推测总耗时。</p>
                ) : null}
              </section>
            </>
          ) : null}
        </div>

        <footer className="drawer-foot">
          <div className="drawer-foot-row">
            <p className="drawer-foot-note">记录为只读，不可编辑</p>
            <button type="button" className="btn btn-primary btn-sm" onClick={onClose}>
              关闭
            </button>
          </div>
        </footer>
      </aside>
    </>
  );
}
