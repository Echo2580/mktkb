import { useEffect, useRef, useState } from 'react';
import { api, errorMessage, isApiError, type UploadResponse } from '../../api/client';
import { Dialog } from '../../components/Dialog';
import { Icon } from '../../components/Icon';
import { formatBytes } from '../../utils/format';
import { UploadDialog, validateUploadFile } from './UploadDialog';

type Status = 'pending' | 'uploading' | 'uploaded' | 'skipped' | 'failed' | 'conflict';

interface Entry {
  id: number;
  file: File;
  path: string;
  status: Status;
  message?: string;
}

const STATUS_LABELS: Record<Status, string> = {
  pending: '等待上传', uploading: '正在上传', uploaded: '已上传，等待处理',
  skipped: '已跳过', failed: '上传失败', conflict: '同名待确认',
};

/** 目录选择时 File.name 是叶子名；显示和排序使用相对路径。 */
function pathOf(file: File): string {
  return file.webkitRelativePath || file.name;
}

/** 代码点排序：不依赖浏览器 ICU/区域设置，队列顺序在相同目录结构下可复现。 */
function compareFolders(left: File, right: File): number {
  const a = pathOf(left);
  const b = pathOf(right);
  return a < b ? -1 : a > b ? 1 : 0;
}

interface Props {
  onClose: () => void;
  onUploaded: (receipts: UploadResponse[]) => void;
}

export function FolderUploadDialog({ onClose, onUploaded }: Props) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resolving, setResolving] = useState<Entry | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const running = useRef(false);
  const stopRequested = useRef(false);
  const directorySupported = 'webkitdirectory' in document.createElement('input');

  useEffect(() => () => { stopRequested.current = true; }, []);

  function update(id: number, change: Partial<Entry>) {
    setEntries((previous) => previous.map((entry) => entry.id === id ? { ...entry, ...change } : entry));
  }

  function chooseFolder(files: FileList | null) {
    if (!files || running.current) return;
    const selected = Array.from(files).sort(compareFolders);
    setEntries(selected.map((file, id) => {
      const message = validateUploadFile(file);
      return { id, file, path: pathOf(file), status: message ? 'skipped' : 'pending', message: message ?? undefined };
    }));
    setError(selected.length ? null : '所选文件夹中没有文件，请重新选择。');
  }

  async function uploadBatch(retryFailed = false) {
    if (running.current) return;
    const queue = entries.filter((entry) => entry.status === (retryFailed ? 'failed' : 'pending'));
    if (!queue.length) return;
    running.current = true;
    stopRequested.current = false;
    setBusy(true);
    setStopping(false);
    setError(null);
    const receipts: UploadResponse[] = [];
    try {
      for (const entry of queue) {
        if (stopRequested.current) break;
        update(entry.id, { status: 'uploading', message: undefined });
        try {
          const receipt = await api.uploadDocument(entry.file);
          receipts.push(receipt);
          update(entry.id, { status: 'uploaded' });
        } catch (caught) {
          if (isApiError(caught) && caught.code === 'DUPLICATE_CONTENT') {
            update(entry.id, { status: 'skipped', message: '内容已存在，未创建重复资料。' });
          } else if (isApiError(caught) && caught.code === 'SAME_NAME_REQUIRES_ACTION') {
            update(entry.id, { status: 'conflict', message: '需要选择替换现有资料或作为独立资料新增。' });
          } else {
            update(entry.id, { status: 'failed', message: errorMessage(caught) });
            if (isApiError(caught) && (caught.status === 401 || caught.status === 403)) {
              setError('登录状态或权限已变化，已停止后续上传。请确认登录后重试。');
              break;
            }
          }
        }
      }
    } finally {
      running.current = false;
      setBusy(false);
      setStopping(false);
      if (receipts.length) onUploaded(receipts);
    }
  }

  const count = (status: Status) => entries.filter((entry) => entry.status === status).length;
  const pending = count('pending');
  const uploaded = count('uploaded');
  const failed = count('failed');

  if (resolving) {
    return <UploadDialog mode="create" initialFile={resolving.file}
      onClose={() => setResolving(null)}
      onUploaded={(receipt) => {
        update(resolving.id, { status: 'uploaded', message: undefined });
        onUploaded([receipt]);
        setResolving(null);
      }} />;
  }

  return (
    <Dialog title="上传文件夹" description="包含子文件夹中的文件；上传后仍需检查并确认发布。"
      onClose={busy ? () => undefined : onClose}
      footer={<>
        <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>关闭</button>
        {busy ? (
          <button type="button" className="btn btn-secondary" disabled={stopping} onClick={() => {
            stopRequested.current = true;
            setStopping(true);
          }}>{stopping ? '等待当前文件完成…' : '停止后续上传'}</button>
        ) : <>
          {failed > 0 ? <button type="button" className="btn btn-secondary" onClick={() => void uploadBatch(true)}>重试失败文件</button> : null}
          <button type="button" className="btn btn-primary" disabled={!pending} onClick={() => void uploadBatch()}>
            <Icon name="upload" size={14} />{uploaded ? '继续上传' : '开始上传'}
          </button>
        </>}
      </>}>
      <input ref={(input) => { inputRef.current = input; if (input) input.webkitdirectory = true; }}
        type="file" multiple className="sr-only" aria-label="选择要上传的文件夹" disabled={busy}
        onChange={(event) => { chooseFolder(event.target.files); event.target.value = ''; }} />
      <button type="button" className="upload-drop" disabled={busy || !directorySupported} onClick={() => inputRef.current?.click()}>
        <Icon name="folder" size={22} />
        <span className="upload-drop-title">{entries.length ? '重新选择文件夹' : '选择文件夹'}</span>
        <span className="upload-drop-desc">支持 Word、Excel、PDF、PNG、JPG，单文件不超过 20 MB。</span>
        <span className="upload-drop-desc">目录内文件分别上传；无效文件会跳过，同名文件由您确认处理。</span>
      </button>
      {!directorySupported ? <p className="form-error" role="alert">当前浏览器不支持选择文件夹，请使用新版 Chrome 或 Edge，或通过“上传资料”选择单个文件。</p> : null}
      {entries.length ? <>
        <p className="folder-upload-summary" role="status" aria-live="polite">
          共 {entries.length} 个文件 · 待上传 {pending} · 已上传 {uploaded} · 失败 {failed} · 待确认 {count('conflict')} · 已跳过 {count('skipped')}
          {busy ? <><br /><span className="spinner spinner-sm" aria-hidden="true" /> 正在逐个上传文件…</> : null}
        </p>
        <ul className="folder-upload-list" aria-label="文件夹上传明细">
          {entries.map((entry) => <li className="chosen-file" key={entry.id}>
            <Icon name="file-text" size={16} />
            <div className="chosen-file-main">
              <p className="file-name folder-upload-path">{entry.path}</p>
              <p className={`file-sub folder-upload-status is-${entry.status}`}>
                {formatBytes(entry.file.size)} · {STATUS_LABELS[entry.status]}
              </p>
              {entry.message ? <p className="form-help">{entry.message}</p> : null}
              {entry.status === 'conflict' ? <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => setResolving(entry)}>处理同名文件</button> : null}
            </div>
          </li>)}
        </ul>
      </> : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
    </Dialog>
  );
}
