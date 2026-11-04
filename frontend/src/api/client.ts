import type { components } from './schema';

export type Schema = components['schemas'];
export type User = Schema['UserPublic'];
export type SessionResponse = Schema['SessionResponse'];
export type ConversationSummary = Schema['ConversationSummary'];
export type ConversationList = Schema['ConversationList'];
export type MessageList = Schema['MessageList'];

/** S2：枚举分页（后端向后兼容扩展；旧 schema 未生成该字段时由本地类型补齐）。 */
export interface PaginationView {
  page: number;
  page_size: number;
  total: number;
  returned: number;
  has_more: boolean;
  next_page?: number | null;
}

export type MessageView = Schema['MessageView'] & { pagination?: PaginationView | null };
export type AskResult = Schema['AskResult'] & { pagination?: PaginationView | null };
export type SourceSummary = Schema['SourceSummary'];
export type SourceView = Schema['SourceView'];
export type DocumentList = Schema['DocumentList'];
export type DocumentSummary = Schema['DocumentSummary'];
export type DocumentDetail = Schema['DocumentDetail'];
export type VersionSummary = Schema['VersionSummary'];
export type JobStatus = Schema['JobStatus'];
export type PreviewResponse = Schema['PreviewResponse'];
export type SourceUnitPublic = Schema['SourceUnitPublic'];
export type UploadResponse = Schema['UploadResponse'];
export type Publication = Schema['Publication'];
export type Deletion = Schema['Deletion'];
export type VersionState = NonNullable<VersionSummary['state']>;

export type ApiErrorPayload = {
  code: string;
  message: string;
  retryable: boolean;
  details: Record<string, unknown> | null;
};

const API_PREFIX = '/api/v1';

let csrfToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}

export function onUnauthorized(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly retryable: boolean;
  readonly details: Record<string, unknown> | null;
  readonly requestId: string | null;

  constructor(
    code: string,
    message: string,
    status: number,
    options: {
      retryable?: boolean;
      details?: Record<string, unknown> | null;
      requestId?: string | null;
    } = {},
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.retryable = options.retryable ?? false;
    this.details = options.details ?? null;
    this.requestId = options.requestId ?? null;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

export function errorMessage(error: unknown): string {
  if (isApiError(error)) {
    return error.requestId ? `${error.message}（请求编号 ${error.requestId.slice(0, 8)}）` : error.message;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return '发生未知错误，请稍后重试';
}

function isEnvelope(value: unknown): value is { error: ApiErrorPayload; request_id?: string } {
  if (typeof value !== 'object' || value === null) return false;
  const error = (value as { error?: unknown }).error;
  return (
    typeof error === 'object' &&
    error !== null &&
    typeof (error as ApiErrorPayload).code === 'string' &&
    typeof (error as ApiErrorPayload).message === 'string'
  );
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'DELETE';
  body?: unknown;
  formData?: FormData;
  signal?: AbortSignal;
  /** 写操作默认携带 CSRF 头；登录与只读请求不需要。 */
  write?: boolean;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? (options.body || options.formData ? 'POST' : 'GET');
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (options.write !== false && method !== 'GET' && csrfToken) {
    headers['X-CSRF-Token'] = csrfToken;
  }

  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}${path}`, {
      method,
      headers,
      credentials: 'same-origin',
      body: options.formData ?? (options.body !== undefined ? JSON.stringify(options.body) : undefined),
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('NETWORK_ERROR', '网络连接失败，请检查网络后重试', 0, { retryable: true });
  }

  if (response.status === 401 && !path.startsWith('/auth/login')) {
    unauthorizedHandler?.();
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get('content-type') ?? '';
  let payload: unknown = null;
  if (contentType.includes('application/json')) {
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
  } else if (!response.ok) {
    // 文件接口失败时也可能返回非 JSON 错误；只保留状态码，不回显响应体。
    payload = null;
  }

  if (!response.ok) {
    const requestId = response.headers.get('X-Request-ID');
    if (isEnvelope(payload)) {
      const error = payload.error;
      throw new ApiError(error.code, error.message, response.status, {
        retryable: Boolean(error.retryable),
        details: error.details ?? null,
        requestId: payload.request_id ?? requestId,
      });
    }
    throw new ApiError(
      response.status >= 500 ? 'INTERNAL_ERROR' : 'HTTP_ERROR',
      response.status >= 500 ? '服务处理失败，请稍后重试' : `请求失败（HTTP ${response.status}）`,
      response.status,
      { retryable: response.status >= 500, requestId },
    );
  }

  return payload as T;
}

export const api = {
  login(username: string, password: string): Promise<SessionResponse> {
    return request<SessionResponse>('/auth/login', {
      method: 'POST',
      body: { username, password },
      write: false,
    });
  },
  me(): Promise<SessionResponse> {
    return request<SessionResponse>('/auth/me');
  },
  logout(): Promise<void> {
    return request<void>('/auth/logout', { method: 'POST', write: true });
  },
  listConversations(offset = 0, limit = 50): Promise<ConversationList> {
    return request<ConversationList>(`/conversations?offset=${offset}&limit=${limit}`);
  },
  createConversation(title?: string): Promise<ConversationSummary> {
    return request<ConversationSummary>('/conversations', {
      method: 'POST',
      body: title ? { title } : {},
    });
  },
  deleteConversation(id: string): Promise<void> {
    return request<void>(`/conversations/${id}`, { method: 'DELETE' });
  },
  listMessages(conversationId: string, offset = 0, limit = 100): Promise<MessageList> {
    return request<MessageList>(`/conversations/${conversationId}/messages?offset=${offset}&limit=${limit}`);
  },
  ask(conversationId: string, clientRequestId: string, question: string, signal?: AbortSignal): Promise<AskResult> {
    return request<AskResult>(`/conversations/${conversationId}/messages`, {
      method: 'POST',
      body: { client_request_id: clientRequestId, question },
      signal,
    });
  },
  getSource(messageId: string, sourceId: string): Promise<SourceView> {
    return request<SourceView>(`/messages/${messageId}/sources/${sourceId}`);
  },
  listDocuments(params: {
    q?: string;
    fileType?: string;
    state?: string;
    offset?: number;
    limit?: number;
  }): Promise<DocumentList> {
    const search = new URLSearchParams();
    if (params.q) search.set('q', params.q);
    if (params.fileType) search.set('file_type', params.fileType);
    if (params.state) search.set('state', params.state);
    search.set('offset', String(params.offset ?? 0));
    search.set('limit', String(params.limit ?? 20));
    return request<DocumentList>(`/documents?${search.toString()}`);
  },
  getDocument(documentId: string): Promise<DocumentDetail> {
    return request<DocumentDetail>(`/documents/${documentId}`);
  },
  uploadDocument(file: File, allowSameName = false): Promise<UploadResponse> {
    const formData = new FormData();
    // 目录选择时 Chromium 的 multipart filename 会带上 webkitRelativePath；显式传叶子名，
    // 避免把本机目录结构发送给服务端，也保证资料名与 File.name 一致。
    formData.append('file', file, file.name);
    if (allowSameName) formData.append('allow_same_name', 'true');
    return request<UploadResponse>('/documents', { method: 'POST', formData });
  },
  uploadVersion(documentId: string, file: File, expectedActiveVersionId?: string | null): Promise<UploadResponse> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    if (expectedActiveVersionId) formData.append('expected_active_version_id', expectedActiveVersionId);
    return request<UploadResponse>(`/documents/${documentId}/versions`, { method: 'POST', formData });
  },
  getJob(jobId: string): Promise<JobStatus> {
    return request<JobStatus>(`/jobs/${jobId}`);
  },
  retryJob(jobId: string): Promise<JobStatus> {
    return request<JobStatus>(`/jobs/${jobId}/retry`, { method: 'POST' });
  },
  preview(
    documentId: string,
    versionId: string,
    params: { offset?: number; limit?: number; sheet?: string; page?: number } = {},
  ): Promise<PreviewResponse> {
    const search = new URLSearchParams();
    search.set('offset', String(params.offset ?? 0));
    search.set('limit', String(params.limit ?? 20));
    if (params.sheet) search.set('sheet', params.sheet);
    if (params.page) search.set('page', String(params.page));
    return request<PreviewResponse>(
      `/documents/${documentId}/versions/${versionId}/preview?${search.toString()}`,
    );
  },
  publish(
    documentId: string,
    versionId: string,
    body: { expected_active_version_id: string | null; expected_revision: number },
  ): Promise<Publication> {
    return request<Publication>(`/documents/${documentId}/versions/${versionId}/publish`, {
      method: 'POST',
      body,
    });
  },
  cancelVersion(documentId: string, versionId: string): Promise<void> {
    return request<void>(`/documents/${documentId}/versions/${versionId}/cancel`, { method: 'POST' });
  },
  deleteDocument(documentId: string, expectedRevision: number): Promise<Deletion> {
    return request<Deletion>(`/documents/${documentId}?expected_revision=${expectedRevision}`, {
      method: 'DELETE',
    });
  },
};
