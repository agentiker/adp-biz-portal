import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv, type UserConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'
import path from 'node:path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
export default defineConfig(async ({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const isAnalyze = mode === 'analyze'

  // 仅在 analyze 模式下按需加载 rollup-plugin-visualizer，避免常态 dev/build 时
  // 因为 npm workspaces hoist 边界问题导致 Node ESM 解析失败。
  // 使用时请确保 devDependencies 中已声明该包。
  let visualizerPlugin: any = null
  if (isAnalyze) {
    const moduleName = 'rollup-plugin-visualizer'
    const { visualizer } = await import(/* @vite-ignore */ moduleName)
    visualizerPlugin = visualizer({
      open: true,
      filename: 'dist/stats.html',
      gzipSize: true,
      brotliSize: true,
    })
  }

  const config: UserConfig = {
    base: './',
    plugins: [
      vue(),
      vueJsx() as any,
      // 打包分析插件，仅在 --mode analyze 时启用
      visualizerPlugin,
    ].filter(Boolean),
    resolve: {
      alias: [
        { find: '@', replacement: fileURLToPath(new URL('./src', import.meta.url)) },
        // 将 @wangeditor-next/editor 的运行时实现指向自建 bundle
        // 用精确匹配（正则末尾 $），避免同时命中 '@wangeditor-next/editor/dist/css/style.css' 等子路径
        // 类型继续走 node_modules/@wangeditor-next/editor 的 .d.ts（import type 会被编译擦除）
        {
          find: /^@wangeditor\/editor$/,
          replacement: path.resolve(__dirname, 'public/wangeditor.esm.js'),
        },
      ],
      // 确保依赖去重，避免多个 Vue/TDesign 实例
      dedupe: ['vue', 'tdesign-vue-next'],
    },
    // 优化依赖预构建
    optimizeDeps: {
      include: [
        'tdesign-vue-next',
        '@tdesign-vue-next/chat',
        'vue',
        'vue-router',
        'pinia',
        'axios',
        'vue-i18n',
      ],
      // 排除 workspace 包，让其使用源码
      // 排除 @wangeditor-next/editor，避免 Vite 预构建它（会去 node_modules 里找而绕过 alias）
      exclude: ['adp-chat-component', 'adp-widget', '@wangeditor/editor'],
    },
    server: {
      host: '0.0.0.0',
      port: 5174,
      strictPort: true,
      proxy: {
        '/api': {
          target: env.SERVICE_API_URL,
          changeOrigin: true,
          // Legacy ADP routes live at the server root, while the unified
          // platform API intentionally keeps its /api/v1 namespace.
          rewrite: (path) => path.startsWith('/api/v1/') ? path : path.replace(/^\/api/, ''),
        },
      },
    },
  }
  return config
})
