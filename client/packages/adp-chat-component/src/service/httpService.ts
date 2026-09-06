/**
 * HTTP 服务模块
 * 基于 Axios 的请求封装
 */
import axios, { type AxiosInstance, type AxiosRequestConfig, type AxiosResponse } from 'axios';

// ============================================================
// Language header 注入（对齐 gpt-demo ajax.js 的 Language header 注入模式）
// ============================================================

/**
 * 当前语言标识，由 App.vue 通过 setLanguage() 同步。
 * 默认 'zh-CN'，API 请求时自动注入为 HTTP Header `Language`。
 */
let currentLanguage = 'zh-CN';

/**
 * 设置当前语言，同时更新 axios 默认 headers 兜底（确保 configureAxios 重建实例后仍生效）。
 * @param lang - 语言标识，如 'zh-CN'、'en-US'
 */
export const setLanguage = (lang: string) => {
    currentLanguage = lang;
    axiosInstance.defaults.headers.common['Language'] = lang;
};

/**
 * 请求拦截器：在每次请求发出前注入 Language header。
 * 优先级：config.headers.Language（业务方显式传） > 当前 currentLanguage。
 */
const injectLanguageHeader = (config: any) => {
    if (!config.headers) {
        config.headers = {};
    }
    // 若业务方已显式传入 Language，则保留；否则注入当前语言
    if (!config.headers['Language']) {
        config.headers['Language'] = currentLanguage;
    }
    return config;
};

// 默认配置
const defaultConfig: AxiosRequestConfig = {
    timeout: 30000,
    withCredentials: true,
    headers: {
        'Content-Type': 'application/json',
    },
};

// 创建 axios 实例
let axiosInstance: AxiosInstance = axios.create(defaultConfig);

// 标记是否设置了自定义响应拦截器
let hasCustomResponseInterceptor = false;

interface RequestInterceptorHandler {
    onFulfilled?: (config: any) => any;
    onRejected?: (error: any) => any;
}

interface ResponseInterceptorHandler {
    onFulfilled?: (response: AxiosResponse) => any;
    onRejected?: (error: any) => any;
}

const requestInterceptors: RequestInterceptorHandler[] = [];
const responseInterceptors: ResponseInterceptorHandler[] = [];

const applyStoredInterceptors = (instance: AxiosInstance) => {
    requestInterceptors.forEach(({ onFulfilled, onRejected }) => {
        instance.interceptors.request.use(onFulfilled, onRejected);
    });
    responseInterceptors.forEach(({ onFulfilled, onRejected }) => {
        instance.interceptors.response.use(onFulfilled, onRejected);
    });
    hasCustomResponseInterceptor = responseInterceptors.length > 0;
};

/**
 * 配置 axios 实例
 * @param config axios 配置
 */
export const configureAxios = (config: AxiosRequestConfig) => {
    const { apiDetailConfig: _apiDetailConfig, ...axiosConfig } = config as AxiosRequestConfig & {
        apiDetailConfig?: unknown;
    };
    axiosInstance = axios.create({
        ...defaultConfig,
        ...axiosConfig,
    });
    applyStoredInterceptors(axiosInstance);
};

/**
 * 设置请求拦截器
 * @param onFulfilled 成功回调
 * @param onRejected 失败回调
 */
export const setRequestInterceptor = (
    onFulfilled?: (config: any) => any,
    onRejected?: (error: any) => any
) => {
    requestInterceptors.push({ onFulfilled, onRejected });
    axiosInstance.interceptors.request.use(onFulfilled, onRejected);
};

/**
 * 设置响应拦截器
 * @param onFulfilled 成功回调
 * @param onRejected 失败回调
 */
export const setResponseInterceptor = (
    onFulfilled?: (response: AxiosResponse) => any,
    onRejected?: (error: any) => any
) => {
    responseInterceptors.push({ onFulfilled, onRejected });
    hasCustomResponseInterceptor = true;
    axiosInstance.interceptors.response.use(onFulfilled, onRejected);
};

/**
 * HTTP 服务对象
 */
/**
 * 获取当前 axios 实例的 baseURL
 * 用于拼接同域代理 URL（如文件下载）
 */
export const getAxiosBaseURL = (): string => {
    return axiosInstance.defaults.baseURL || '';
};

export const httpService = {
    /**
     * GET 请求
     * @param url 请求地址
     * @param params 请求参数
     * @param config 额外配置
     */
    async get<T = any>(url: string, params?: object, config?: AxiosRequestConfig): Promise<T> {
        const response = await axiosInstance.get(url, { params, ...config });
        // 如果设置了自定义响应拦截器，拦截器已经处理了 response.data
        return (hasCustomResponseInterceptor ? response : response.data) as T;
    },

    /**
     * POST 请求
     * @param url 请求地址
     * @param data 请求数据
     * @param config 额外配置
     */
    async post<T = any>(url: string, data?: object, config?: AxiosRequestConfig): Promise<T> {
        const response = await axiosInstance.post(url, data, config);
        return (hasCustomResponseInterceptor ? response : response.data) as T;
    },

    /**
     * PUT 请求
     * @param url 请求地址
     * @param data 请求数据
     * @param config 额外配置
     */
    async put<T = any>(url: string, data?: object, config?: AxiosRequestConfig): Promise<T> {
        const response = await axiosInstance.put(url, data, config);
        return (hasCustomResponseInterceptor ? response : response.data) as T;
    },

    /**
     * DELETE 请求
     * @param url 请求地址
     * @param config 额外配置
     */
    async delete<T = any>(url: string, config?: AxiosRequestConfig): Promise<T> {
        const response = await axiosInstance.delete(url, config);
        return (hasCustomResponseInterceptor ? response : response.data) as T;
    },
};

export default httpService;

// ============================================================
// 立即注册 Language header 注入拦截器
// 同时推入 requestInterceptors 数组，确保 configureAxios() 重建 axios 实例时
// 通过 applyStoredInterceptors 重新 apply。
// ============================================================
requestInterceptors.push({ onFulfilled: injectLanguageHeader });
axiosInstance.interceptors.request.use(injectLanguageHeader, undefined);
