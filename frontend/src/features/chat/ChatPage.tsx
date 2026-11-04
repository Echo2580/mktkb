import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useOutletContext, useParams } from 'react-router-dom';
import { api, errorMessage, isApiError } from '../../api/client';
import type { AskResult, MessageView } from '../../api/client';
import { useAuth } from '../../app/AuthProvider';
import type { ShellContextValue } from '../../app/AppShell';
import { useToast } from '../../app/ToastProvider';
import { Icon } from '../../components/Icon';
import { SourceDrawer } from '../sources/SourceDrawer';
import { MessageCard } from './MessageCard';

const EXAMPLES = [
  { icon: 'map-pin', question: '城东店的宣传海报放在哪里？' },
  { icon: 'user', question: '城东店的联系人是谁？' },
  { icon: 'list-checks', question: '领取活动物料需要哪些步骤？' },
];

interface Pending {
  requestId: string;
  question: string;
  status: 'sending' | 'error';
  error?: string;
}

interface SourceTarget {
  messageId: string;
  sourceId: string;
  title: string;
}

function newRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return '00000000-0000-4000-8000-' + String(Date.now()).padStart(12, '0').slice(-12);
}

export function ChatPage() {
  const { conversationId } = useParams();
  const shell = useOutletContext<ShellContextValue>();
  const { user } = useAuth();
  const { push } = useToast();
  const navigate = useNavigate();

  const [messages, setMessages] = useState<MessageView[]>([]);
  const [totalMessages, setTotalMessages] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [liveResults, setLiveResults] = useState<Record<string, AskResult>>({});
  const [sourceTarget, setSourceTarget] = useState<SourceTarget | null>(null);
  const [question, setQuestion] = useState('');
  const [composerError, setComposerError] = useState<string | null>(null);
  const [emptyKnowledgeBase, setEmptyKnowledgeBase] = useState(false);

  const inFlight = useRef(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const requestSeq = useRef(0);

  const currentConversation = conversationId
    ? shell.conversations.find((conversation) => conversation.id === conversationId)
    : undefined;
  const firstUserMessage = messages.find((message) => message.role === 'user');
  const threadTitle = currentConversation?.title ?? firstUserMessage?.text ?? '会话记录';

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      const element = scrollRef.current;
      if (element) element.scrollTop = element.scrollHeight;
    });
  }, []);

  const loadMessages = useCallback(
    async (id: string, options: { quiet?: boolean } = {}) => {
      const seq = ++requestSeq.current;
      if (!options.quiet) setLoading(true);
      try {
        const first = await api.listMessages(id, 0, 100);
        let data = first;
        if (first.total > first.items.length) {
          data = await api.listMessages(id, Math.max(0, first.total - 100), 100);
        }
        if (seq !== requestSeq.current) return;
        setMessages(data.items);
        setTotalMessages(data.total);
        setLoadError(null);
      } catch (caught) {
        if (seq !== requestSeq.current) return;
        if (isApiError(caught) && caught.code === 'CONVERSATION_NOT_FOUND') {
          setLoadError('会话不存在或已被删除');
        } else if (isApiError(caught) && caught.code === 'FORBIDDEN') {
          setLoadError('没有访问该会话的权限');
        } else {
          setLoadError(errorMessage(caught));
        }
        throw caught;
      } finally {
        if (!options.quiet) setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    setSourceTarget(null);
    setLiveResults({});
    if (!conversationId) {
      setMessages([]);
      setTotalMessages(0);
      setLoadError(null);
      setLoading(false);
      requestSeq.current += 1;
      return;
    }
    setMessages([]);
    setLoadError(null);
    loadMessages(conversationId).catch(() => undefined);
  }, [conversationId, loadMessages]);

  useEffect(() => {
    if (user?.role !== 'admin') {
      setEmptyKnowledgeBase(false);
      return;
    }
    let cancelled = false;
    api
      .listDocuments({ state: 'published', limit: 1 })
      .then((data) => {
        if (!cancelled) setEmptyKnowledgeBase(data.total === 0);
      })
      .catch(() => {
        // 无法确认时不展示“知识库为空”，避免把权限或网络错误当作空库。
      });
    return () => {
      cancelled = true;
    };
  }, [user?.role]);

  useEffect(() => {
    scrollToBottom();
  }, [messages.length, pending, scrollToBottom]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = '44px';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 128)}px`;
  }, [question]);

  const submit = useCallback(
    async (rawQuestion: string, options: { requestId?: string } = {}) => {
      const text = rawQuestion.trim();
      if (!text) {
        setComposerError('请输入问题后再发送');
        textareaRef.current?.focus();
        return;
      }
      if (text.length > 2000) {
        setComposerError('问题不能超过 2000 个字符');
        return;
      }
      if (inFlight.current) return;
      inFlight.current = true;
      setComposerError(null);
      const requestId = options.requestId ?? newRequestId();
      setPending({ requestId, question: text, status: 'sending' });
      const controller = new AbortController();
      let timedOut = false;
      const timer = window.setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, 75_000);
      try {
        let activeId = conversationId;
        if (!activeId) {
          const created = await api.createConversation(text.slice(0, 200));
          activeId = created.id;
          navigate(`/chat/${created.id}`, { replace: true });
          void shell.reloadConversations();
        }
        const result = await api.ask(activeId, requestId, text, controller.signal);
        setLiveResults((previous) => ({ ...previous, [result.message_id]: result }));
        setQuestion('');
        const userMessage: MessageView = {
          id: `local-user-${requestId}`,
          role: 'user',
          text,
          created_at: new Date().toISOString(),
          sources: [],
        };
        const assistantMessage: MessageView = {
          id: result.message_id,
          role: 'assistant',
          text: result.text,
          kind: result.kind,
          revision: result.revision,
          error_code: result.error_code,
          missing_fields: result.missing_fields ?? [],
          created_at: new Date().toISOString(),
          sources: result.sources ?? [],
        };
        try {
          await loadMessages(activeId, { quiet: true });
        } catch {
          setMessages((previous) =>
            previous.some((message) => message.id === result.message_id)
              ? previous
              : [...previous, userMessage, assistantMessage],
          );
          push('回答已完成，但消息列表刷新失败；当前页面显示本次结果，刷新后可重新读取。', 'error');
        }
        void shell.reloadConversations();
        setPending(null);
        scrollToBottom();
      } catch (caught) {
        setPending({
          requestId,
          question: text,
          status: 'error',
          error: timedOut
            ? '请求超过 75 秒未返回。服务端可能仍在处理；点击“重试本次提问”会复用同一请求编号，不会重复生成回答。'
            : errorMessage(caught),
        });
      } finally {
        window.clearTimeout(timer);
        inFlight.current = false;
      }
    },
    [conversationId, loadMessages, navigate, push, scrollToBottom, shell],
  );

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit(question);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      if (!inFlight.current) void submit(question);
    }
  }

  function fillExample(text: string) {
    setQuestion(text);
    setComposerError(null);
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      const textarea = textareaRef.current;
      if (textarea) textarea.setSelectionRange(text.length, text.length);
    });
  }

  function editQuestion(text: string) {
    setQuestion(text);
    setComposerError(null);
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(text.length, text.length);
    });
  }

  const retryNow = useCallback(
    (text: string) => {
      if (inFlight.current) return;
      void submit(text);
    },
    [submit],
  );

  const overLimit = question.length > 2000;
  const sendDisabled = inFlight.current || question.trim().length === 0 || overLimit;

  return (
    <>
      <div className="chat-scroll" ref={scrollRef}>
        {conversationId ? (
          <div className="chat-container">
            <div className="chat-thread-head">
              <div className="chat-thread-title-wrap">
                <h2 className="chat-thread-title">{threadTitle}</h2>
                <span className="chat-thread-tag">会话记录</span>
              </div>
              <button
                type="button"
                className="btn btn-secondary btn-md"
                onClick={() => {
                  if (conversationId) void loadMessages(conversationId).catch(() => undefined);
                }}
              >
                <Icon name="rotate-cw" size={13} />
                刷新消息
              </button>
            </div>

            {loading ? (
              <div className="empty-state" role="status">
                <span className="spinner" aria-hidden="true" />
                <p className="empty-desc" style={{ marginTop: 10 }}>
                  正在加载会话消息…
                </p>
              </div>
            ) : loadError ? (
              <div className="notice notice-error" role="alert">
                <Icon name="alert-circle" size={15} className="notice-icon" />
                <div className="notice-body">
                  <p>{loadError}</p>
                  <div className="notice-actions">
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadMessages(conversationId).catch(() => undefined)}>
                      重试
                    </button>
                    <Link className="btn btn-ghost btn-sm" to="/chat">
                      新建对话
                    </Link>
                  </div>
                </div>
              </div>
            ) : messages.length === 0 && !pending ? (
              <div className="empty-state">
                <span className="empty-icon">
                  <Icon name="message-square" size={20} />
                </span>
                <p className="empty-title">这个会话还没有消息</p>
                <p className="empty-desc">在下方输入问题开始查询；回答只依据当前已发布资料。</p>
              </div>
            ) : (
              <div className="message-list" aria-live="polite">
                {totalMessages > messages.length ? (
                  <p className="conversation-caption" style={{ paddingLeft: 46 }}>
                    仅显示最近 {messages.length} 条消息（共 {totalMessages} 条）
                  </p>
                ) : null}
                {messages.map((message, index) => {
                  const preceding = [...messages.slice(0, index)]
                    .reverse()
                    .find((candidate) => candidate.role === 'user');
                  return (
                    <MessageCard
                      key={message.id}
                      message={message}
                      questionBefore={preceding?.text}
                      liveResult={liveResults[message.id]}
                      onOpenSource={(messageId, sourceId, title) => setSourceTarget({ messageId, sourceId, title })}
                      onRetryQuestion={retryNow}
                      onEditQuestion={editQuestion}
                    />
                  );
                })}
              </div>
            )}

            {pending ? (
              <div className="message-list" style={{ marginTop: 24 }} aria-live="polite">
                <div className="message-user">
                  <div className="message-user-bubble">{pending.question}</div>
                  <p className="message-time">{pending.status === 'sending' ? '正在发送…' : '发送未完成'}</p>
                </div>
                {pending.status === 'sending' ? (
                  <div className="message-assistant">
                    <div className="assistant-avatar" aria-hidden="true">
                      <Icon name="sparkles" size={15} />
                    </div>
                    <div className="assistant-body">
                      <div className="assistant-head">
                        <span className="assistant-name">知识库回答</span>
                        <span className="message-time">刚刚</span>
                      </div>
                      <div className="typing" role="status">
                        <span className="spinner" aria-hidden="true" />
                        <span>正在查找资料…</span>
                        <span className="typing-hint">检索已发布资料</span>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="message-assistant">
                    <div className="assistant-avatar" aria-hidden="true">
                      <Icon name="alert-circle" size={15} />
                    </div>
                    <div className="assistant-body">
                      <div className="assistant-head">
                        <span className="assistant-name">提问未完成</span>
                        <span className="badge badge-rose">
                          <span className="badge-dot" />
                          请求失败
                        </span>
                      </div>
                      <div className="answer-card is-error">
                        <p className="answer-text" style={{ fontSize: 14 }}>
                          {pending.error}
                        </p>
                        <p className="answer-subtle">
                          请求编号 {pending.requestId.slice(0, 8)} 会在重试时复用；若服务端已经完成，此操作只取回原结果，不会重复提问。
                        </p>
                        <div className="state-actions">
                          <button
                            type="button"
                            className="btn btn-primary btn-md"
                            onClick={() => void submit(pending.question, { requestId: pending.requestId })}
                          >
                            <Icon name="refresh-cw" size={13} />
                            重试本次提问
                          </button>
                          <button type="button" className="btn btn-secondary btn-md" onClick={() => editQuestion(pending.question)}>
                            <Icon name="pencil-line" size={13} />
                            修改问题
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ) : null}
          </div>
        ) : (
          <div className="chat-container">
            <section className="welcome" aria-labelledby="welcome-title">
              <div>
                <div className="welcome-mark">
                  <Icon name="sparkles" size={21} />
                </div>
                <h2 className="welcome-title" id="welcome-title">
                  有什么需要查询的？
                </h2>
                <p className="welcome-desc">查询物品位置、店家信息和部门流程，回答会附上当前有效资料与来源。</p>

                {emptyKnowledgeBase ? (
                  <div className="notice notice-warning welcome-banner">
                    <Icon name="alert-triangle" size={15} className="notice-icon" />
                    <div className="notice-body">
                      <p>知识库暂无已发布资料，员工问答暂时没有可查询内容。</p>
                      <div className="notice-actions">
                        <Link className="btn btn-primary btn-sm" to="/documents">
                          <Icon name="upload" size={13} />
                          上传并发布资料
                        </Link>
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>

              <section className="example-section" aria-labelledby="example-title">
                <div className="example-head">
                  <h3 className="example-title" id="example-title">
                    示例问题
                  </h3>
                  <span className="example-hint">点击填入输入框</span>
                </div>
                <div className="example-grid">
                  {EXAMPLES.map((example) => (
                    <button
                      key={example.question}
                      type="button"
                      className="example-card"
                      onClick={() => fillExample(example.question)}
                    >
                      <span className="example-card-top">
                        <span className="example-icon">
                          <Icon name={example.icon} size={16} />
                        </span>
                        <Icon name="arrow-up-right" size={15} className="example-arrow" />
                      </span>
                      <span className="example-text">{example.question}</span>
                    </button>
                  ))}
                </div>
              </section>
            </section>
          </div>
        )}
      </div>

      <footer className="composer">
        <div className="composer-inner">
          <div className="composer-label-row">
            <label className="composer-label" htmlFor="question-input">
              输入你的问题
            </label>
            <span className="composer-hint">
              Enter 发送 · Shift + Enter 换行
              {question.length > 1800 ? ` · ${question.length}/2000` : ''}
            </span>
          </div>
          <form
            className="composer-box"
            onSubmit={handleSubmit}
          >
            <div className="composer-row">
              <textarea
                ref={textareaRef}
                id="question-input"
                className="composer-textarea"
                placeholder="描述你想查询的物品、门店或流程…"
                rows={1}
                value={question}
                onChange={(event) => {
                  setQuestion(event.target.value);
                  setComposerError(null);
                }}
                onKeyDown={handleKeyDown}
                aria-invalid={overLimit || Boolean(composerError)}
                aria-describedby={composerError ? 'composer-error' : undefined}
                disabled={inFlight.current && pending?.status === 'sending'}
              />
              <button className="btn btn-primary" type="submit" disabled={sendDisabled}>
                <span>发送</span>
                <Icon name="arrow-up" size={15} />
              </button>
            </div>
          </form>
          {composerError || overLimit ? (
            <p className="form-error" id="composer-error" role="alert" style={{ marginTop: 8 }}>
              <Icon name="alert-circle" size={14} className="notice-icon" />
              <span>{overLimit ? '问题不能超过 2000 个字符' : composerError}</span>
            </p>
          ) : null}
          <p className="composer-note">
            <Icon name="shield-check" size={13} />
            <span>回答依据当前已发布资料，请核对来源与生效时间；页面不保存或展示模型密钥。</span>
          </p>
        </div>
      </footer>

      {sourceTarget ? (
        <SourceDrawer
          messageId={sourceTarget.messageId}
          sourceId={sourceTarget.sourceId}
          title={sourceTarget.title}
          onClose={() => setSourceTarget(null)}
        />
      ) : null}
    </>
  );
}
