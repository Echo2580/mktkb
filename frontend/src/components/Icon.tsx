import type { SVGProps } from 'react';

const PATHS: Record<string, string[]> = {
  'book-open': [
    'M12 7v14',
    'M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z',
  ],
  sparkles: [
    'm12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z',
    'M5 3v4',
    'M19 17v4',
    'M3 5h4',
    'M17 19h4',
  ],
  files: [
    'M20 7h-3a2 2 0 0 1-2-2V2',
    'M9 18a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h7l4 4v10a2 2 0 0 1-2 2Z',
    'M3 7.6v12.8A1.6 1.6 0 0 0 4.6 22h9.8',
  ],
  plus: ['M5 12h14', 'M12 5v14'],
  'message-square': ['M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'],
  'log-out': ['M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4', 'm16 17 5-5-5-5', 'M21 12H9'],
  'map-pin': ['M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0'],
  user: ['M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2', 'circle:12,7,4'],
  'user-round': ['circle:12,8,5', 'M20 21a8 8 0 0 0-16 0'],
  'list-checks': ['m3 17 2 2 4-4', 'm3 7 2 2 4-4', 'M13 6h8', 'M13 12h8', 'M13 18h8'],
  'arrow-up-right': ['M7 7h10v10', 'M7 17 17 7'],
  'arrow-up': ['m5 12 7-7 7 7', 'M12 19V5'],
  'arrow-left': ['m12 19-7-7 7-7', 'M19 12H5'],
  'arrow-right': ['M5 12h14', 'm12 5 7 7-7 7'],
  'link-2': ['M9 17H7A5 5 0 0 1 7 7h2', 'M15 7h2a5 5 0 1 1 0 10h-2', 'M8 12h8'],
  'scan-eye': [
    'M3 7V5a2 2 0 0 1 2-2h2',
    'M17 3h2a2 2 0 0 1 2 2v2',
    'M21 17v2a2 2 0 0 1-2 2h-2',
    'M7 21H5a2 2 0 0 1-2-2v-2',
    'circle:12,12,1',
    'M18.944 12.33a1 1 0 0 0 0-.66 7.5 7.5 0 0 0-13.888 0 1 1 0 0 0 0 .66 7.5 7.5 0 0 0 13.888 0',
  ],
  'shield-check': [
    'M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1 1 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z',
    'm9 12 2 2 4-4',
  ],
  check: ['M20 6 9 17l-5-5'],
  'check-circle': ['M21.801 10A10 10 0 1 1 17 3.335', 'm9 11 3 3L22 4'],
  x: ['M18 6 6 18', 'm6 6 12 12'],
  'file-text': [
    'M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z',
    'M14 2v4a2 2 0 0 0 2 2h4',
    'M10 9H8',
    'M16 13H8',
    'M16 17H8',
  ],
  'file-spreadsheet': [
    'M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z',
    'M14 2v4a2 2 0 0 0 2 2h4',
    'M8 13h2',
    'M14 13h2',
    'M8 17h2',
    'M14 17h2',
  ],
  'file-type-2': [
    'M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z',
    'M14 2v4a2 2 0 0 0 2 2h4',
    'M9 13v-1h6v1',
    'M12 12v6',
    'M11 18h2',
  ],
  image: ['rect:3,3,18,18,2', 'circle:9,9,2', 'm21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21'],
  upload: ['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'M17 8l-5-5-5 5', 'M12 3v12'],
  'upload-cloud': [
    'M12 13v8',
    'M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242',
    'm8 17 4-4 4 4',
  ],
  search: ['circle:11,11,8', 'm21 21-4.3-4.3'],
  'search-x': ['m13.5 8.5-5 5', 'm8.5 8.5 5 5', 'circle:11,11,8', 'm21 21-4.3-4.3'],
  'trash-2': [
    'M3 6h18',
    'M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6',
    'M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2',
    'M10 11v6',
    'M14 11v6',
  ],
  'refresh-cw': [
    'M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8',
    'M21 3v5h-5',
    'M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16',
    'M8 16H3v5',
  ],
  'rotate-cw': ['M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8', 'M21 3v5h-5'],
  'rotate-ccw': ['M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8', 'M3 3v5h5'],
  'alert-triangle': ['m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z', 'M12 9v4', 'M12 17h.01'],
  'alert-circle': ['circle:12,12,10', 'M12 8v4', 'M12 16h.01'],
  info: ['circle:12,12,10', 'M12 16v-4', 'M12 8h.01'],
  'loader-circle': ['M21 12a9 9 0 1 1-6.219-8.56'],
  clock: ['circle:12,12,10', 'M12 6v6l4 2'],
  history: ['M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8', 'M3 3v5h5', 'M12 7v5l4 2'],
  lock: ['rect:3,11,18,11,2', 'M7 11V7a5 5 0 0 1 10 0v4'],
  menu: ['M4 6h16', 'M4 12h16', 'M4 18h16'],
  'chevron-right': ['m9 18 6-6-6-6'],
  'chevron-left': ['m15 18-6-6 6-6'],
  'chevron-down': ['m6 9 6 6 6-6'],
  'git-branch': ['M6 3v12', 'circle:18,6,3', 'circle:6,18,3', 'M18 9a9 9 0 0 1-9 9'],
  'git-compare': ['circle:18,18,3', 'circle:6,6,3', 'M13 6h3a2 2 0 0 1 2 2v7', 'M11 18H8a2 2 0 0 1-2-2V9'],
  'clipboard-check': [
    'rect:8,2,8,4,1',
    'M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2',
    'm9 14 2 2 4-4',
  ],
  'table-2': [
    'M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18m0 0h10a2 2 0 0 0 2-2V9M9 21H5a2 2 0 0 1-2-2V9m0 0h18',
  ],
  store: [
    'm2 7 4.41-4.41A2 2 0 0 1 7.83 2h8.34a2 2 0 0 1 1.42.59L22 7',
    'M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8',
    'M15 22v-4a2 2 0 0 0-2-2h-2a2 2 0 0 0-2 2v4',
    'M2 7h20',
    'M22 7v3a2 2 0 0 1-2 2 2 2 0 0 1-2-2 2 2 0 0 1-2 2 2 2 0 0 1-2-2 2 2 0 0 1-2 2 2 2 0 0 1-2-2 2 2 0 0 1-2 2 2 2 0 0 1-2-2V7',
  ],
  'mouse-pointer-click': ['m9 9 5 12 1.8-5.2L21 14Z', 'M7.2 2.2 8 5.1', 'M5.1 8 2.2 7.2', 'M14 4.1 12 6', 'M6 12l-1.9 2'],
  'pencil-line': ['M12 20h9', 'M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z'],
  'corner-down-left': ['m9 10-5 5 5 5', 'M20 4v7a4 4 0 0 1-4 4H4'],
  ban: ['circle:12,12,10', 'm4.9 4.9 14.2 14.2'],
  highlighter: ['m9 11-6 6v3h9l3-3', 'm22 12-4.6 4.6a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8L14 4'],
  'minus-circle': ['circle:12,12,10', 'M8 12h8'],
  'layout-grid': ['rect:3,3,7,7,1', 'rect:14,3,7,7,1', 'rect:14,14,7,7,1', 'rect:3,14,7,7,1'],
  'external-link': ['M15 3h6v6', 'M10 14 21 3', 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6'],
  send: ['m22 2-7 20-4-9-9-4Z', 'M22 2 11 13'],
  eye: ['M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z', 'circle:12,12,3'],
  dot: ['circle-fill:12,12,2'],
  'circle-dot': ['circle:12,12,10', 'circle-fill:12,12,2'],
  'circle-slash': ['circle:12,12,10', 'm9 9 6 6'],
  'file-warning': ['M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z', 'M12 9v4', 'M12 17h.01'],
  folder: ['M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z'],
  inbox: ['M22 12h-6l-2 3h-4l-2-3H2', 'M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z'],
};

function renderShape(token: string, key: string) {
  const [name, raw] = token.split(':');
  const numbers = raw.split(',').map(Number);
  if (name === 'circle') {
    return <circle key={key} cx={numbers[0]} cy={numbers[1]} r={numbers[2]} />;
  }
  if (name === 'circle-fill') {
    return <circle key={key} cx={numbers[0]} cy={numbers[1]} r={numbers[2]} fill="currentColor" stroke="none" />;
  }
  if (name === 'rect') {
    return (
      <rect
        key={key}
        x={numbers[0]}
        y={numbers[1]}
        width={numbers[2]}
        height={numbers[3]}
        rx={numbers[4] ?? 0}
      />
    );
  }
  return null;
}

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'name'> {
  name: keyof typeof PATHS | string;
  size?: number;
}

export function Icon({ name, size = 16, className, ...rest }: IconProps) {
  const paths = PATHS[name];
  if (!paths) {
    return (
      <svg
        aria-hidden="true"
        className={className}
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        {...rest}
      >
        <circle cx="12" cy="12" r="9" />
      </svg>
    );
  }
  return (
    <svg
      aria-hidden="true"
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...rest}
    >
      {paths.map((token, index) => (token.includes(':') ? renderShape(token, `${name}-${index}`) : <path key={`${name}-${index}`} d={token} />))}
    </svg>
  );
}

export function fileIconFor(name: string): { icon: string; label: string; tile: string; badge: string } {
  const extension = name.split('.').pop()?.toLowerCase() ?? '';
  if (extension === 'xlsx') {
    return { icon: 'file-spreadsheet', label: 'Excel', tile: 'tile-emerald', badge: 'badge-emerald' };
  }
  if (extension === 'docx') {
    return { icon: 'file-text', label: 'Word', tile: 'tile-blue', badge: 'badge-blue' };
  }
  if (extension === 'pdf') {
    return { icon: 'file-type-2', label: 'PDF', tile: 'tile-rose', badge: 'badge-rose' };
  }
  if (['png', 'jpg', 'jpeg'].includes(extension)) {
    return { icon: 'image', label: '图片', tile: 'tile-violet', badge: 'badge-violet' };
  }
  return { icon: 'file-text', label: '文件', tile: 'tile-slate', badge: 'badge-slate' };
}
