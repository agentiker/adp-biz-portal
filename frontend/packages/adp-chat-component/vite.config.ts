import { defineConfig, type UserConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'
import { createSvgIconsPlugin } from 'vite-plugin-svg-icons'
import dts from 'vite-plugin-dts'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
export default defineConfig(async ({ mode }) => {
  const isAnalyze = mode === 'analyze'

  // 仅在 analyze 模式下按需加载 rollup-plugin-visualizer，避免常态构建依赖它。
  // 用变量名隐藏模块字面量，跳过 TS 静态解析（该包不在依赖中，仅 analyze 模式才会用到，
  // 使用前请先 `npm i -D rollup-plugin-visualizer`）。
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
    plugins: [
      vue(), 
      vueJsx(),
      dts({
        // 指定要编译的 TypeScript 配置文件
        tsconfigPath: './tsconfig.app.json',
        // 输出目录
        outDir: 'dist/types',
        // 包含的文件
        include: ['src/**/*.ts', 'src/**/*.tsx', 'src/**/*.vue'],
        // 排除的文件
        exclude: ['src/**/*.spec.ts', 'src/**/*.test.ts'],
        // 在构建后清理输出目录
        cleanVueFileName: true,
        // 生成类型声明文件后的回调
        afterBuild: () => {
          console.log('Type declarations generated successfully!')
        }
      }),
      createSvgIconsPlugin({
        // 指定需要缓存的图标文件夹（绝对路径）
        iconDirs: [path.resolve(__dirname, 'src/assets/icons')],
        // 指定 symbolId 的生成格式
        symbolId: 'icon-[name]',
        // （可选）自定义 SVG 雪碧图插入到 HTML 的位置
        inject: 'body-last',
        // （可选）自定义 SVG 雪碧图的 DOM 元素 ID
        customDomId: '__svg__icons__dom__',
      }),
      // 打包分析插件，仅在 --mode analyze 时启用
      visualizerPlugin,
    ].filter(Boolean),
    resolve: {
      alias: {
        '@': path.resolve(__dirname, 'src'),
      },
    },
    server: {
      port: 3000,
    },
    build: {
      outDir: 'dist/es',
      lib: {
        entry: path.resolve(__dirname, 'src/index.ts'),
        name: 'ADPChatComponent',
        // 只产 ES。不显式限定时 Vite 默认 ['es','umd']，UMD 会强制打开
        // inlineDynamicImports，与 manualChunks 冲突并把整图压成单文件。
        formats: ['es'],
      },
      rollupOptions: {
        // 外部化依赖，不打包进库。UMD 自包含产物已下线，唯一消费者
        // （平台管理端 app）自带 vue 与 tdesign。
        external: ['vue', 'tdesign-vue-next', '@tdesign-vue-next/chat'],
        output: {
          format: 'es',
          entryFileNames: 'adp-chat-component.es.js',
          // 使用相对路径，确保 chunk 可以被正确加载
          chunkFileNames: 'chunks/[name]-[hash].js',
          assetFileNames: (assetInfo: { name?: string }) => {
            if (assetInfo.name === 'style.css') return 'adp-chat-component.css'
            return assetInfo.name || 'assets/[name]-[hash][extname]'
          },
          // 手动分包：大体积资源单独打包
          manualChunks(id: string) {
            // katex 分包
            if (id.includes('katex')) {
              return 'katex'
            }
          },
        },
      },
      cssCodeSplit: false,
    },
    define: {
      'process.env.NODE_ENV': JSON.stringify('production'),
    },
  }
  return config
})

