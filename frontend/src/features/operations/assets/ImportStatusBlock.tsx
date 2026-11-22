/** T305 抽屉“导入状态”三态块：失败红 / 待审核琥珀 / 正常绿。只渲染接口实际返回的字段。 */
import { Link } from 'react-router-dom';
import { Icon } from '../../../components/Icon';
import type { AssetDetail, DocumentItem } from './assetsApi';
import { describeImportStatus } from './assetModel';

const TONE_ICON: Record<string, string> = {
  failed: 'alert-triangle',
  pending: 'clock',
  normal: 'check-circle',
  unknown: 'info',
};

export function ImportStatusBlock({
  detail,
  item,
}: {
  detail: AssetDetail | null;
  item: DocumentItem | null;
}) {
  const status = describeImportStatus(detail, item);
  return (
    <div className={`asset-import asset-import-${status.tone}`} data-testid="ops-import-status" data-tone={status.tone}>
      <p className="asset-import-headline" data-testid="ops-import-headline">
        <Icon name={TONE_ICON[status.tone] ?? 'info'} size={14} />
        {status.headline}
      </p>
      <p className="asset-import-body">{status.body}</p>
      {status.tone === 'failed' ? (
        <dl className="asset-import-facts">
          <div>
            <dt>失败环节</dt>
            <dd data-testid="ops-import-stage">{status.stage}</dd>
          </div>
          <div>
            <dt>error_code</dt>
            <dd data-testid="ops-import-error">{status.errorCode}</dd>
          </div>
          {status.message ? (
            <div>
              <dt>可展示原因</dt>
              <dd data-testid="ops-import-message">{status.message}</dd>
            </div>
          ) : null}
          <div>
            <dt>继续生效</dt>
            <dd>{status.activeNumber !== null ? `V${status.activeNumber}` : '当前无生效版本'}</dd>
          </div>
        </dl>
      ) : null}
      {status.tone === 'failed' ? (
        <Link className="asset-inline-link" to="/documents">
          可前往资料管理重新上传
        </Link>
      ) : null}
    </div>
  );
}
