import type { AxiosRequestConfig } from "axios";
import { Capacitor } from "@capacitor/core";
import { API_BASE_URL, apiClient } from "./client";

// Orval custom instance mutator (httpClient: "axios" mode)
// Wraps the existing apiClient so all interceptors (auth, guild header) are preserved.
// With httpClient: "axios", Orval calls this with (config, options) where config
// is an AxiosRequestConfig-like object { url, method, data, params, headers, signal }.
// Generated URLs already include the full /api/v1 prefix, so on web we set baseURL
// to "" to avoid double-prefixing with the apiClient's own baseURL.
// On native (Capacitor), we must use the configured server origin so requests
// reach the actual backend instead of the WebView's own origin.
export const apiMutator = <T>(
  config: AxiosRequestConfig,
  options?: AxiosRequestConfig
): Promise<T> => {
  const baseURL = Capacitor.isNativePlatform() ? API_BASE_URL.replace(/\/api\/v1\/?$/, "") : "";
  const merged = options
    ? { ...config, ...options, headers: { ...config.headers, ...options.headers }, baseURL }
    : { ...config, baseURL };
  return apiClient<T>(merged).then(({ data }) => data);
};

export default apiMutator;

export type ErrorType<Error> = Error;
export type BodyType<BodyData> = BodyData;
