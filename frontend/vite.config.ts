import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const backendOrigin = process.env.T08_BACKEND_ORIGIN || 'http://127.0.0.1:8077';

// 开发/测试时由 Vite 代理 /api 到本机后端，浏览器侧保持同源：
// Cookie、Origin 与 CSRF 校验都按真实部署（同源反向代理）语义执行。
const proxy = {
  '/api': {
    target: backendOrigin,
    changeOrigin: false,
  },
};

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy,
    watch: {
      ignored: ['**/.e2e-data/**', '**/playwright-report/**', '**/test-results/**'],
    },
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    strictPort: true,
    proxy,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    target: 'es2022',
  },
});
