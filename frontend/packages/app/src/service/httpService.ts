import axiosInstance from './axiosInstance'
import type { AxiosRequestConfig } from 'axios'

// 说明：axiosInstance 的响应拦截器已将返回值解包为业务数据（response.data），
// 运行时这里拿到的就是 T；显式 as 断言是对该行为的类型标注，
// 同时规避不同 axios 小版本返回类型命名差异（AxiosResponse / AxiosResponseResult）导致的编译失败。
export const httpService = {
  get: async <T>(url: string, params?: object): Promise<T> => {
    return axiosInstance.get(url, { params }) as unknown as T
  },

  post: async <T>(url: string, data: object, config?: AxiosRequestConfig): Promise<T> => {
    return axiosInstance.post(url, data, config) as unknown as T
  },

  put: async <T>(url: string, data: object): Promise<T> => {
    return axiosInstance.put(url, data) as unknown as T
  },

  delete: async <T>(url: string): Promise<T> => {
    return axiosInstance.delete(url) as unknown as T
  },

  patch: async <T>(url: string, data: object): Promise<T> => {
    return axiosInstance.patch(url, data) as unknown as T
  },
}

export default httpService
