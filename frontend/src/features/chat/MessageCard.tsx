import type { AskResult, MessageView, SourceSummary } from '../../api/client';
import { Icon, fileIconFor } from '../../components/Icon';
import {
  SOURCE_STATUS_LABELS,
  formatDateTime,
  formatTime,
  resultBadgeLabel,
  resultKindTone,
} from '../../utils/format';

/** 服务端明确不可重试的稳定码；历史消息没有 retryable 字段，只能按码推导。 */
const NON_RETRYABLE_SERVICE_ERROR_CODES = new Set([
  'MODEL_NOT_CONFIGURED',
  'MODEL_BUDGET_REFUSED',
  'QA_INTERNAL_ERROR',
  'INVALID_QUERY',
]);

interface MessageCardProps {
  message: MessageView;
  questionBefore?: string;
  liveResult?: AskResult;
  onOpenSource: (messageId: string, sourceId: string, title: string) => void;
  onRetryQuestion: (question: string) => void;
  onEditQuestion: (question: string) => void;
}

function toneBadgeClass(tone: string): string {
  return `badge badge-${tone}`;
}

function sourceFor(sources: SourceSummary[], sourceId: string): SourceSummary | undefined {
  return sources.find((source) => source.source_id === sourceId);
}

function sourceLocatorText(locator: Record<string, unknown>): string {
  const parts: string[] = [];
  if (typeof locator.sheet === 'string' && locator.sheet) parts.push(`工作表 ${locator.sheet}`);
  if (typeof locator.page === 'number') parts.push(`第 ${locator.page} 页`);
  if (typeof locator.paragraph === 'number') parts.push(`第 ${locator.paragraph} 段`);
  if (typeof locator.row === 'number') parts.push(`第 ${locator.row} 行`);
  return parts.join(' · ');
}

export function MessageCard({ message, questionBefore, liveResult, onOpenSource, onRetryQuestion, onEditQuestion }: MessageCardProps) {
  if (message.role === 'user') {
    return (
      <div className="message-user">
        <div className="message-user-bubble">{message.text}</div>
        <p className="message-time">发送于 {formatTime(message.created_at)}</p>
      </div>
    );
  }

  const kind = message.kind ?? 'answer';
  const sources = message.sources ?? [];
  const live = liveResult && liveResult.message_id === message.id ? liveResult : undefined;
  const liveCandidates = live?.candidates ?? [];
  const liveConflicts = live?.conflicts ?? [];
  const candidates = liveCandidates.length > 0 ? liveCandidates : (message.candidates ?? []);
  const conflicts = liveConflicts.length > 0 ? liveConflicts : (message.conflicts ?? []);
  const missing = message.missing_fields ?? [];
  const cardClass =
    kind === 'conflict' || kind === 'clarification'
      ? 'answer-card is-warning'
      : kind === 'service_error'
        ? 'answer-card is-error'
        : kind === 'knowledge_changed'
          ? 'answer-card is-info'
          : 'answer-card';

  const errorCode = live?.error_code ?? message.error_code ?? null;
  // 历史消息没有 retryable 字段（MessageView 字段集不得新增），只能按稳定码推导；
  // 实时结果以服务端 retryable 为准。MODEL_OUTPUT_INVALID 重试同一问题不会改变结果。
  const retryable =
    errorCode !== 'MODEL_OUTPUT_INVALID' &&
    (live ? live.retryable : !NON_RETRYABLE_SERVICE_ERROR_CODES.has(errorCode ?? ''));
  const pagination = live?.pagination ?? message.pagination ?? null;
  const nextPage = pagination?.has_more && pagination.next_page ? pagination.next_page : null;

  return (
    <article className="message-assistant" aria-label="知识库回答">
      <div className="assistant-avatar" aria-hidden="true">
        <Icon name="sparkles" size={15} />
      </div>
      <div className="assistant-body">
        <div className="assistant-head">
          <span className="assistant-name">知识库回答</span>
          {message.kind ? (
            <span className={toneBadgeClass(resultKindTone(kind))}>
              <span className="badge-dot" />
              {resultBadgeLabel(kind, candidates.length, errorCode)}
            </span>
          ) : null}
          <span className="message-time">{formatTime(message.created_at)}</span>
        </div>

        <div className={cardClass}>
          <p className="answer-text">{message.text}</p>

          {kind === 'answer' && missing.length > 0 ? (
            <dl className="field-list">
              {missing.map((field) => (
                <div className="field-row" key={field}>
                  <dt className="field-key">{field}</dt>
                  <dd className="field-value is-missing">
                    <Icon name="minus-circle" size={12} />
                    未记录
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}

          {kind === 'answer' && nextPage ? (
            <div className="state-actions">
              <button type="button" className="btn btn-secondary btn-md" onClick={() => onRetryQuestion(`第 ${nextPage} 页`)}>
                <Icon name="list-checks" size={13} />
                查看第 {nextPage} 页（共 {pagination?.total ?? 0} 条）
              </button>
            </div>
          ) : null}

          {kind === 'answer' && missing.length > 0 ? (
            <p className="state-note">
              <Icon name="clock" size={12} />
              以上字段在当前已发布资料中没有记录，系统不会推测或补写。
            </p>
          ) : null}

          {kind === 'clarification' ? (
            <>
              {candidates.length > 0 ? (
                <div className="candidate-row" role="group" aria-label="选择候选">
                  {candidates.map((candidate) => (
                    <button
                      key={`${candidate.label}-${candidate.followup_question}`}
                      type="button"
                      className="candidate-button"
                      onClick={() => onRetryQuestion(candidate.followup_question)}
                      aria-label={`选择 ${candidate.label}：${candidate.followup_question}`}
                    >
                      <Icon name="store" size={14} />
                      {candidate.label}
                    </button>
                  ))}
                </div>
              ) : (
                <p className="state-note">
                  <Icon name="info" size={12} />
                  这次回答没有提供可选项，无法直接点选；请按上方提示补充门店、物品或更具体的条件后重新提问。
                </p>
              )}
            </>
          ) : null}

          {kind === 'not_found' ? (
            <>
              <div className="state-note" style={{ display: 'block' }}>
                <p style={{ fontWeight: 600, color: 'var(--slate-600)', marginBottom: 4 }}>建议你可以：</p>
                <ul style={{ margin: 0, paddingLeft: 18, lineHeight: '20px' }}>
                  <li>补充准确的门店、物品或流程名称后重新查询</li>
                  <li>或联系管理员补充相应资料</li>
                </ul>
              </div>
              {questionBefore ? (
                <div className="state-actions">
                  <button type="button" className="btn btn-secondary btn-md" onClick={() => onEditQuestion(questionBefore)}>
                    <Icon name="pencil-line" size={13} />
                    修改原问题后重试
                  </button>
                </div>
              ) : null}
            </>
          ) : null}

          {kind === 'conflict' ? (
            <>
              {conflicts.length > 0 ? (
                conflicts.map((conflict) => (
                  <div className="conflict-block" key={conflict.field}>
                    <p className="conflict-field">字段：{conflict.field}</p>
                    <div className="conflict-entries">
                      {conflict.entries.map((entry) => {
                        const source = sourceFor(sources, entry.source_id);
                        const locatorText = source ? sourceLocatorText(source.locator) : '';
                        return (
                          <div
                            className="conflict-entry"
                            key={`${conflict.field}-${entry.source_id}-${entry.value}`}
                            style={{ alignItems: 'flex-start' }}
                          >
                            <div style={{ minWidth: 0 }}>
                              <p className="conflict-value">{entry.value}</p>
                              {source ? (
                                <>
                                  <p className="conflict-source" style={{ marginTop: 4 }}>
                                    {source.document_name} · V{source.version_number}
                                    <span
                                      className={`badge ${
                                        source.status === 'active'
                                          ? 'badge-emerald'
                                          : source.status === 'deleted'
                                            ? 'badge-rose'
                                            : 'badge-slate'
                                      }`}
                                      style={{ marginLeft: 6 }}
                                    >
                                      {SOURCE_STATUS_LABELS[source.status] ?? source.status}
                                    </span>
                                  </p>
                                  <p className="conflict-source" style={{ marginTop: 2 }}>
                                    {locatorText ? `${locatorText} · ` : ''}
                                    生效时间 {formatDateTime(source.published_at)}
                                  </p>
                                </>
                              ) : (
                                <p className="conflict-source" style={{ marginTop: 4 }}>
                                  该历史消息未保存此来源明细，无法打开依据；请重新提问核对。
                                </p>
                              )}
                            </div>
                            {source ? (
                              <button
                                type="button"
                                className="btn btn-secondary btn-sm"
                                onClick={() => onOpenSource(message.id, source.source_id, source.document_name)}
                              >
                                <Icon name="scan-eye" size={12} />
                                查看依据
                              </button>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))
              ) : (
                <p className="state-note">
                  <Icon name="info" size={12} />
                  该历史消息未保存冲突明细；请重新提问以核对各来源的当前取值。
                </p>
              )}
              <p className="state-note">
                <Icon name="alert-triangle" size={12} />
                系统不会按上传时间自动裁定；请核对各冲突来源或联系管理员核实。
              </p>
            </>
          ) : null}

          {kind === 'service_error' ? (
            <>
              <div className="state-note" style={{ background: 'var(--rose-50)', color: 'var(--rose-800)' }}>
                <Icon name="alert-circle" size={12} />
                <span>
                  本次问答未完成，这不是资料中没有答案。
                  {errorCode ? `错误码：${errorCode}。` : ''}
                  {errorCode === 'MODEL_OUTPUT_INVALID'
                    ? '模型输出未通过来源校验，已拒绝展示，重新提问不会改变结果。'
                    : errorCode === 'INVALID_QUERY'
                      ? '这是查询条件问题，不是服务故障；请换个说法后重新提问。'
                      : retryable
                        ? '可稍后重新提问；服务端不会因重试而重复保存同一条回答。'
                        : '这类失败重试同一问题不会自行恢复；请按错误码联系管理员处理，或修改问题后重试。'}
                </span>
              </div>
              <div className="state-actions">
                {questionBefore && retryable ? (
                  <button type="button" className="btn btn-primary btn-md" onClick={() => onRetryQuestion(questionBefore)}>
                    <Icon name="refresh-cw" size={13} />
                    重新提问
                  </button>
                ) : null}
                {questionBefore ? (
                  <button type="button" className="btn btn-secondary btn-md" onClick={() => onEditQuestion(questionBefore)}>
                    <Icon name="pencil-line" size={13} />
                    修改问题
                  </button>
                ) : null}
              </div>
            </>
          ) : null}

          {kind === 'knowledge_changed' ? (
            <>
              <div className="state-note" style={{ background: 'var(--blue-50)', color: 'var(--blue-800)' }}>
                <Icon name="refresh-cw" size={12} />
                <span>回答生成期间资料版本发生变化，本次回答已中止，未保存旧事实。请基于最新有效资料重新查询。</span>
              </div>
              {questionBefore ? (
                <div className="state-actions">
                  <button type="button" className="btn btn-primary btn-md" onClick={() => onRetryQuestion(questionBefore)}>
                    <Icon name="search" size={13} />
                    重新查询
                  </button>
                </div>
              ) : null}
            </>
          ) : null}

          {sources.length > 0 && kind !== 'conflict' ? (
            <div className="source-section">
              <div className="source-section-head">
                <span className="source-section-title">
                  <Icon name="link-2" size={13} />
                  来源与依据
                </span>
                <span className="source-section-hint">
                  生效时间与发送时间分开显示{typeof message.revision === 'number' ? ` · 知识库版本 ${message.revision}` : ''}
                </span>
              </div>
              <div className="source-bars">
                {sources.map((source, index) => {
                  const meta = fileIconFor(source.document_name);
                  return (
                    <div className="source-bar" key={source.source_id}>
                      <span className="source-bar-icon">
                        <Icon name={meta.icon} size={14} />
                      </span>
                      <div className="source-bar-main">
                        <p className="source-bar-title">
                          {sources.length > 1 ? <span className="source-bar-index">[{index + 1}]</span> : null}
                          <span className="source-bar-name" title={source.document_name}>
                            {source.document_name}
                          </span>
                          <span className="source-bar-version">V{source.version_number}</span>
                        </p>
                        <p className="source-bar-meta">
                          {meta.label} · 状态 {source.status === 'active' ? '有效' : source.status === 'deleted' ? '已删除' : '已被替换'} ·
                          生效时间 {formatDateTime(source.published_at)}
                        </p>
                      </div>
                      <span
                        className={`badge ${
                          source.status === 'active' ? 'badge-emerald' : source.status === 'deleted' ? 'badge-rose' : 'badge-slate'
                        }`}
                      >
                        {source.status === 'active' ? '有效' : source.status === 'deleted' ? '已删除' : '已替换'}
                      </span>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => onOpenSource(message.id, source.source_id, source.document_name)}
                      >
                        <Icon name="scan-eye" size={12} />
                        查看依据
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}

          {kind === 'answer' && sources.length === 0 ? (
            <p className="state-note" style={{ background: 'var(--rose-50)', color: 'var(--rose-800)' }}>
              <Icon name="alert-triangle" size={12} />
              本次回答未返回可核对来源，请勿直接引用；可重新提问或检查资料状态。
            </p>
          ) : null}
        </div>
      </div>
    </article>
  );
}
