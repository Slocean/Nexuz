import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// 打包分流（docs/headless_server.md）：
//   npm run build          → 桌面版产物 dist/（PyInstaller 桌面包用）
//   npm run build:server   → 服务器版产物 dist-server/（backend/server.py 托管）
// 两种构建各自烘焙目标标记（__NEXUZ_TARGET__），桌面产物不含任何
// 服务器桥接行为，服务器产物积木面板由服务端按 requires 过滤。
export default defineConfig(({ mode }) => {
  const target = mode === 'server' ? 'server' : 'desktop';
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src')
      }
    },
    define: {
      __NEXUZ_TARGET__: JSON.stringify(target)
    },
    build: {
      outDir: target === 'server' ? 'dist-server' : 'dist',
      emptyOutDir: true
    },
    server: {
      host: '127.0.0.1',
      port: 2342,
      strictPort: true
    },
    base: './'
  };
});
