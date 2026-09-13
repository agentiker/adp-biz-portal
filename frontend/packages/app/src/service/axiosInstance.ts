import axios from 'axios';
import router from '@/router'
import { logout } from '@/service/login';
import { getBaseURL } from '@/utils/url';
import { useUiStore } from '@/stores/ui';

// 创建axios实例
const instance = axios.create({
  baseURL: getBaseURL(),
  timeout: 1000 * 60, // 请求超时时间
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
instance.interceptors.request.use(
  (config) => {
    // 注入 Language header（对齐 gpt-demo ajax.js 的 Language header 注入模式）
    // 从 Pinia store 读取当前语言：'zh' → 'zh-CN', 'en' → 'en-US'
    // 若业务方已显式传入 Language，则保留
    if (!config.headers['Language']) {
      const uiStore = useUiStore();
      config.headers['Language'] = uiStore.language === 'en' ? 'en-US' : 'zh-CN';
    }
    return config
  },
  (error) => {
    // 对请求错误做些什么
    return Promise.reject(error)
  },
)

// 响应拦截器
instance.interceptors.response.use(
  (response) => {
    // 对响应数据做点什么
    return response.data
  },
  async (error) => {
    // 如果是stream响应
    if (
      error.response &&
      error.response.config &&
      error.response.config.responseType === 'stream'
    ) {
      try {
        // 将流转换为文本
        const data = await new Response(error.response.data).text()
        // 替换为转换后的数据
        if (error.response.headers['content-type'] === 'application/json') {
          error.response.data = JSON.parse(data)
        } else {
          error.response.data = data
        }
      } catch (e) {
        console.error('stream转换失败:', e)
      }
    } else if (error.response) {
      // 对响应错误做点什么
      // 服务器返回了错误状态码
      console.error('API Error:', error.response.status, error.response.data)
    } else {
      console.error('Network Error:', error.message)
    }
    console.log('[error] axio',error)
    if (error.response && error.response.status === 401 && !String(error.config?.url || '').includes('/api/v1/auth/logout')) {
      void logout(() => router.replace({ name: 'login' }));
    }
    return Promise.reject(error)
  },
)

// workaround for webkit bug 194379 (https://bugs.webkit.org/show_bug.cgi?id=194379)
if (!(ReadableStream.prototype as any)[Symbol.asyncIterator]) {
  (ReadableStream.prototype as any)[Symbol.asyncIterator] = async function* () {
    const reader = this.getReader();
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) return;
        yield value;
      }
    } finally {
      reader.releaseLock();
    }
  };
}
export default instance
