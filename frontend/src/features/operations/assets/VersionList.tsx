/** T305 抽屉“版本列表”：逐版本元信息与导入摘要，不展示其他版本内容。 */
import type { AssetDetail } from './assetsApi';
import { formatMoment, importForVersion, stageLabel, versionStateBadge } from './assetModel';

const JOB_STATE_LABELS: Record<string, string> = {
  queued: '排队中',
  running: '进行中',
  succeeded: '已完成',
  failed: '失败',
  blocked: '阻断',
  cancelled: '已取消',
};

export function VersionList({ detail }: { detail: AssetDetail }) {
  const versions = [...(detail.versions ?? [])].sort((a, b) => b.number - a.number);
  const activeId = detail.document.active_version_id ?? null;

  if (versions.length === 0) {
    return (
      <div className="asset-version-empty" data-testid="ops-version-empty">
        接口未返回版本记录。
      </div>
    );
  }

  return (
    <div className="asset-version-list" data-testid="ops-version-list">
      {versions.map((version) => {
        const badge = versionStateBadge(version.state);
        const job = importForVersion(detail, version.version_id);
        return (
          <div
            key={version.version_id}
            className={`asset-version-row${version.version_id === activeId ? ' is-active' : ''}`}
            data-testid="ops-version-row"
            data-version-id={version.version_id}
            data-version-number={version.number}
            data-version-state={version.state}
          >
            <div className="asset-version-line">
              <span className="asset-version-number">V{version.number}</span>
              <span className={`badge ${badge.badge}`} data-testid="ops-version-state">
                {badge.label}
              </span>
              {version.version_id === activeId ? <span className="asset-version-current">当前生效</span> : null}
              <span className="asset-version-time">
                {version.published_at
                  ? `发布 ${formatMoment(version.published_at)}`
                  : `上传 ${formatMoment(version.uploaded_at)}`}
              </span>
            </div>
            <div className="asset-version-meta">
              {version.published_at ? <span>上传 {formatMoment(version.uploaded_at)}</span> : null}
              {job ? (
                <span data-testid="ops-version-import">
                  导入{JOB_STATE_LABELS[job.state] ?? job.state} · {stageLabel(job.stage)}
                  {job.error_code ? ` · ${job.error_code}` : ''}
                </span>
              ) : (
                <span className="asset-muted">导入记录未记录</span>
              )}
            </div>
            {job?.message ? <p className="asset-version-message">{job.message}</p> : null}
          </div>
        );
      })}
    </div>
  );
}
