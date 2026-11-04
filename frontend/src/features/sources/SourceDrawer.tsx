import { useEffect, useState } from 'react';
import { api, errorMessage, isApiError } from '../../api/client';
import type { SourceView } from '../../api/client';
import { Drawer } from '../../components/Dialog';
import { Icon, fileIconFor } from '../../components/Icon';
import {
  SOURCE_STATUS_LABELS,
  formatDateTime,
  locatorParts,
} from '../../utils/format';

interface SourceDrawerProps {
  messageId: string;
  sourceId: string;
  title: string;
  onClose: () => void;
}

interface UnavailableInfo {
  status: string;
  documentName: string;
  versionNumber: number;
}

export function SourceDrawer({ messageId, sourceId, title, onClose }: SourceDrawerProps) {
  const [source, setSource] = useState<SourceView | null>(null);
  const [unavailable, setUnavailable] = useState<UnavailableInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fileMeta = fileIconFor(title);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      setUnavailable(null);
      try {
        const data = await api.getSource(messageId, sourceId);
        if (!cancelled) setSource(data);
      } catch (caught) {
        if (cancelled) return;
        if (isApiError(caught) && caught.status === 410) {
          const details = (caught.details ?? {}) as Record<string, unknown>;
          setUnavailable({
            status: typeof details.status === 'string' ? details.status : 'deleted',
            documentName: typeof details.document_name === 'string' ? details.document_name : title,
            versionNumber: typeof details.version_number === 'number' ? details.version_number : 0,
          });
        } else {
          setError(errorMessage(caught));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [messageId, sourceId, title]);

  const subtitle = source
    ? `${source.document_name} · V${source.version_number}`
    : unavailable
      ? `${unavailable.documentName} · V${unavailable.versionNumber}`
      : title;

  return (
    <Drawer
      title="来源详情"
      subtitle={subtitle}
      narrow
      onClose={onClose}
      closeLabel="关闭来源详情"
      icon={
        <span className={`tile ${unavailable ? 'tile-slate' : fileMeta.tile}`}>
          <Icon name={unavailable ? 'ban' : fileMeta.icon} size={16} />
        </span>
      }
      footer={
        <div className="drawer-foot-row">
          <p className="drawer-foot-note" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Icon name="lock" size={12} />
            来源为只读资料，不支持编辑
          </p>
          <button type="button" className="btn btn-secondary btn-md" onClick={onClose}>
            关闭来源
          </button>
        </div>
      }
    >
      {loading ? (
        <div className="empty-state">
          <span className="spinner" aria-hidden="true" />
          <p className="empty-desc" style={{ marginTop: 10 }}>
            正在读取来源…
          </p>
        </div>
      ) : unavailable ? (
        <div>
          <div className="answer-card is-error" style={{ marginTop: 0 }}>
            <p className="answer-text" style={{ fontSize: 15 }}>
              来源已失效，内容不可访问
            </p>
            <p className="answer-subtle">
              该来源当前状态为「{SOURCE_STATUS_LABELS[unavailable.status] ?? unavailable.status}」，系统只保留文件名、版本与失效状态，
              不再提供提取内容、原图或原件入口。
            </p>
          </div>
          <div className="detail-grid" style={{ marginTop: 14 }}>
            <div className="detail-cell">
              <p className="detail-label">资料</p>
              <p className="detail-value">{unavailable.documentName}</p>
            </div>
            <div className="detail-cell">
              <p className="detail-label">版本</p>
              <p className="detail-value">V{unavailable.versionNumber}</p>
            </div>
            <div className="detail-cell">
              <p className="detail-label">失效状态</p>
              <p className="detail-value">
                <span className="badge badge-slate">{SOURCE_STATUS_LABELS[unavailable.status] ?? unavailable.status}</span>
              </p>
            </div>
          </div>
          <p className="state-note">
            <Icon name="info" size={12} />
            历史回答文字仍保留当时内容，但不会再作为当前事实依据；如需最新信息请重新提问。
          </p>
        </div>
      ) : error ? (
        <div className="notice notice-error" role="alert">
          <Icon name="alert-circle" size={15} className="notice-icon" />
          <div className="notice-body">
            <p>无法读取来源详情</p>
            <p style={{ marginTop: 4 }}>{error}</p>
          </div>
        </div>
      ) : source ? (
        <div>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
            <div style={{ minWidth: 0 }}>
              <h3 style={{ fontSize: 15, fontWeight: 600, color: 'var(--slate-900)', overflowWrap: 'anywhere' }}>
                {source.document_name}
              </h3>
              <p style={{ marginTop: 4, color: 'var(--slate-500)', fontSize: 11 }}>
                {fileMeta.label} · 第 {source.version_number} 版
              </p>
            </div>
            <span
              className={`badge ${
                source.status === 'active' ? 'badge-emerald' : source.status === 'deleted' ? 'badge-rose' : 'badge-slate'
              }`}
            >
              <span className="badge-dot" />
              {SOURCE_STATUS_LABELS[source.status] ?? source.status}
            </span>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, marginTop: 12, fontSize: 11, color: 'var(--slate-500)' }}>
            <span className="badge badge-slate">{fileMeta.label}</span>
            <span className="badge badge-slate">V{source.version_number}</span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <Icon name="clock" size={12} />
              生效 {formatDateTime(source.published_at)}
            </span>
          </div>

          <div className="fact-box">
            <p className="fact-box-title">
              <Icon name="highlighter" size={12} />
              本次引用的内容
            </p>
            <p className="fact-box-text">{source.text?.trim() ? source.text : '该来源未提供可展示的文本片段。'}</p>
          </div>

          <div className="detail-section">
            <p className="detail-section-title">
              <Icon name="map-pin" size={13} />
              来源定位
            </p>
            <div className="locator-list">
              {locatorParts(source.locator).length > 0 ? (
                locatorParts(source.locator).map((part) => (
                  <span className="locator-chip" key={part.key}>
                    {part.label} {part.value}
                  </span>
                ))
              ) : (
                <span className="locator-chip">服务端未提供定位信息</span>
              )}
            </div>
          </div>

          {source.fields && Object.keys(source.fields).length > 0 ? (
            <div className="detail-section">
              <p className="detail-section-title">
                <Icon name="table-2" size={13} />
                记录字段（原始值）
              </p>
              <div style={{ marginTop: 8, border: '1px solid var(--slate-200)', borderRadius: 8, overflow: 'hidden' }}>
                <table className="preview-table">
                  <thead>
                    <tr>
                      <th scope="col">字段</th>
                      <th scope="col">值</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(source.fields).map(([key, value]) => (
                      <tr key={key}>
                        <td style={{ width: '30%', color: 'var(--slate-500)' }}>{key}</td>
                        <td>{typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          {source.warnings && source.warnings.length > 0 ? (
            <div className="detail-section">
              <p className="detail-section-title">
                <Icon name="alert-triangle" size={13} />
                解析提示
              </p>
              <ul style={{ marginTop: 8, paddingLeft: 18, color: 'var(--amber-800)', fontSize: 12, lineHeight: '20px' }}>
                {source.warnings.map((warning, index) => (
                  <li key={`${warning}-${index}`}>{warning}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="detail-section">
            <p className="detail-section-title">
              <Icon name="external-link" size={13} />
              受保护原件
            </p>
            {source.file_url ? (
              <>
                <a
                  className="btn btn-secondary btn-sm"
                  href={source.file_url}
                  target="_blank"
                  rel="noreferrer"
                  style={{ marginTop: 8, display: 'inline-flex' }}
                >
                  <Icon name="eye" size={13} />
                  在新窗口打开原件
                </a>
                <p className="detail-section-hint">
                  原件接口会再次校验当前账号与来源有效性；失效或他人消息的来源会被服务端拒绝。
                </p>
              </>
            ) : (
              <p className="detail-section-hint">服务端未提供原件入口。</p>
            )}
          </div>
        </div>
      ) : null}
    </Drawer>
  );
}
