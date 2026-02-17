import { apiClient } from "./client";

// Orval custom instance mutator
// Wraps the existing apiClient so all interceptors (auth, guild header) are preserved.
// Orval calls this with (url, { method, headers, data, params, signal, ... }).
// We accept a generic record to avoid type conflicts between fetch's RequestInit
// and Axios's AxiosRequestConfig that Orval may pass in.
export const apiMutator = <T>(url: string, options?: Record<string, unknown>): Promise<T> => {
  return apiClient<T>({
    url,
    method: options?.method as string,
    data: options?.data ?? options?.body,
    params: options?.params,
    headers: options?.headers as Record<string, string>,
    signal: options?.signal as AbortSignal,
  }).then(({ data }) => data);
};

export default apiMutator;

export type ErrorType<Error> = Error;
export type BodyType<BodyData> = BodyData;
