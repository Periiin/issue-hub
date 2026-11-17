import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期前端跑 5175，API/附件走代理到后端 8090；
// 生产构建后由 FastAPI 直接托管 dist，同源不需要代理。
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5175,
    proxy: {
      '/api': 'http://127.0.0.1:8090',
      '/files': 'http://127.0.0.1:8090'
    }
  },
  build: { outDir: 'dist', emptyOutDir: true }
})
