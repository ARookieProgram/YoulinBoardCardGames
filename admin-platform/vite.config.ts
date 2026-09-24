import { fileURLToPath, URL } from 'node:url'

import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')

  // 后端 Django 服务地址。前端不直接拼这个地址，而是通过下面的代理转发，
  // 这样浏览器侧始终是同源请求：
  //   * 开发期不需要配置 CORS；
  //   * 不受跨域 Cookie / 预检影响；
  //   * 生产环境把同一份配置换成真实域名或网关即可。
  const backend = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'

  return {
    plugins: [vue(), vueDevTools()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    build: {
      // Element Plus 与 Vue 全家桶单独拆成 chunk：
      // 业务代码改动时，用户不必重新下载这两个大依赖。
      //
      // 注意：Vite 8 的打包器是 **Rolldown**，不是 Rollup——
      // 它的 `output.manualChunks` 只接受函数形式，对象形式会直接报
      // `TypeError: manualChunks is not a function`，所以这里用 Rolldown 的
      // `advancedChunks.groups`。新增分组时 `test` 用正则或模块 id 数组。
      rollupOptions: {
        output: {
          advancedChunks: {
            groups: [
              {
                name: 'element-plus',
                test: /[\\/]node_modules[\\/](element-plus|@element-plus)[\\/]/,
              },
              {
                name: 'vue',
                test: /[\\/]node_modules[\\/](vue|vue-router|pinia|@vue)[\\/]/,
              },
            ],
          },
        },
      },
      // Element Plus 是全量引入的（见 src/main.ts），它自己的 chunk 必然超过
      // 默认的 500 kB 阈值。这类 chunk 的文件名带内容哈希，改动业务代码时不会
      // 失效，所以这个体积是可接受的——把阈值提到它之上，避免每次构建都刷警告。
      // 真要减体积，得改成按需引入 Element Plus。
      chunkSizeWarningLimit: 1200,
    },
    server: {
      port: 5173,
      proxy: {
        // 管理平台后端（platform_server）的接口都在 /api 下。
        '/api': {
          target: backend,
          changeOrigin: true,
        },
        // Django 自带的数据库管理站点（/admin/），方便本机排查数据。
        '/admin': {
          target: backend,
          changeOrigin: true,
        },
      },
    },
  }
})
