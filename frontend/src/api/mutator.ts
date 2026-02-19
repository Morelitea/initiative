import type { AxiosRequestConfig } from "axios";
import { apiClient } from "./client";

// Orval custom instance mutator (httpClient: "axios" mode)
// Wraps the existing apiClient so all interceptors (auth, guild header) are preserved.
// With httpClient: "axios", Orval calls this with (config, options) where config
// is an AxiosRequestConfig-like object { url, method, data, params, headers, signal }.
// Generated URLs already include the full /api/v1 prefix, so we set baseURL to ""
// to avoid double-prefixing with the apiClient's own baseURL.
export const apiMutator = <T>(
  config: AxiosRequestConfig,
  _options?: AxiosRequestConfig // eslint-disable-line @typescript-eslint/no-unused-vars
): Promise<T> => {
  return apiClient<T>({ ...config, baseURL: "" }).then(({ data }) => data);
};

export default apiMutator;

export type ErrorType<Error> = Error;
export type BodyType<BodyData> = BodyData;
