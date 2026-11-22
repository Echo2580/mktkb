/** T305 资产抽屉（右侧 520px）：版本列表 + 导入状态块 + 引用卡，Esc/遮罩关闭，全页只读。 */
import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Icon } from '../../../components/Icon';
import type { AssetDetail, DocumentItem } from './assetsApi';
import { activeVersion, fileTypeMeta, formatMoment } from './assetModel';
import { ImportStatusBlock } from './ImportStatusBlock';
import { VersionList } from './VersionList';

export interface CitationSummary {
  finalCitations: number | null;
  relatedRequests: number | null;
}

export function AssetDrawer({
  documentId,
  detail,
  item,
  loading,
  error,
  windowLabelText,
  requestsHref,
  versionRequestsHref,
  citation,
  onClose,
}: {
  documentId: string;
  detail: AssetDetail | null;
  item: DocumentItem | null;
  loading: boolean;
  error: string | null;
  windowLabelText: string;
  requestsHref: string;
  versionRequestsHref: string | null;
  citation: CitationSummary;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const meta = fileTypeMeta(detail?.document.file_type ?? item?.file_type);
  const versions = detail?.versions ?? [];
  const active = activeVersion(detail);
  const title = detail?.document.name ?? item?.name ?? '资料详情';
  const related = citation.relatedRequests;
  const finals = citation.finalCitations;
  const conflictAssociation = related !== null && finals !== null && related > finals;

  return (
    <div className="asset-drawer-root" data-testid="ops-asset-drawer">
      <div className="asset-drawer-scrim" onClick={onClose} aria-hidden="true" />
      <aside
        className="asset-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="asset-drawer-title"
        data-document-id={documentId}
      >
        <header className="asset-drawer-head">
          <div className="asset-drawer-heading">
            <h2 className="asset-drawer-title" id="asset-drawer-title" data-testid="ops-drawer-title">
              {title}
            </h2>
            <p className="asset-drawer-meta" data-testid="ops-drawer-meta">
              {meta.label} · {versions.length} 个版本 ·{' '}
              {active ? `当前生效 V${active.number}` : '当前无生效版本'} · 只读
            </p>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="关闭资产详情"
            data-testid="ops-drawer-close"
            onClick={onClose}
          >
            <Icon name="x" size={18} />
          </button>
        </header>

        <div className="asset-drawer-body">
          {loading ? (
            <p className="ops-loading" role="status" data-testid="ops-drawer-loading">
              <span className="spinner spinner-sm" aria-hidden="true" />
              正在读取资料详情…
            </p>
          ) : null}

          {error && !loading ? (
            <div className="notice notice-error" role="alert" data-testid="ops-drawer-error">
              <Icon name="alert-circle" size={16} className="notice-icon" />
              <div className="notice-body">
                <p>{error}</p>
                <p className="asset-muted">关闭后可重新打开该资料。</p>
              </div>
            </div>
          ) : null}

          {detail && !loading ? (
            <>
              <section className="asset-section" aria-label="版本列表">
                <div className="asset-section-head">
                  <p className="asset-section-title">版本列表</p>
                  <span className="badge badge-plain">只读</span>
                </div>
                <VersionList detail={detail} />
              </section>

              <section className="asset-section" aria-label="导入状态">
                <p className="asset-section-title">导入状态</p>
                <ImportStatusBlock detail={detail} item={item} />
              </section>

              <section className="asset-ref-card" aria-label="引用情况" data-testid="ops-ref-card">
                <div className="asset-ref-head">
                  <p className="asset-ref-label">{windowLabelText} 被引用</p>
                  <p className="asset-ref-value">
                    <span data-testid="ops-ref-count">{finals ?? '—'}</span>
                    <span className="asset-ref-unit"> 次</span>
                  </p>
                </div>
                <p className="asset-ref-related" data-testid="ops-related-count">
                  {related === null || finals === null
                    ? '该资料不在当前筛选列表内，窗口引用数未加载。'
                    : conflictAssociation
                      ? `相关问答 ${related} 条（含冲突关联，不计入最终引用）`
                      : `相关问答 ${related} 条（窗口内最终引用）`}
                </p>
                <div className="asset-ref-actions">
                  <Link className="btn btn-secondary btn-sm" to={requestsHref} data-testid="ops-ref-link">
                    <Icon name="message-square" size={14} />
                    查看关联问答
                  </Link>
                  {versionRequestsHref ? (
                    <Link className="asset-inline-link" to={versionRequestsHref} data-testid="ops-ref-version-link">
                      按生效版本查看
                    </Link>
                  ) : null}
                </div>
                <p className="asset-ref-note">
                  引用次数为所选窗口内最终引用（排除冲突问答）；生效版本与待审核为当前库存口径，不随窗口回溯。最近发布时间：
                  {formatMoment(active?.published_at ?? detail.document.last_published_at)}
                </p>
              </section>

              <p className="asset-drawer-note">
                资产数据来自资料管理的发布记录；导入失败的版本不会参与问答，也不会替换当前生效版本。
              </p>
            </>
          ) : null}
        </div>

        <footer className="asset-drawer-foot">
          <Link className="btn btn-secondary btn-sm" to="/documents" data-testid="ops-doc-link">
            <Icon name="folder" size={14} />
            前往资料管理
          </Link>
          <button type="button" className="btn btn-primary btn-sm" onClick={onClose}>
            关闭
          </button>
        </footer>
      </aside>
    </div>
  );
}
