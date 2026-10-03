import { Capacitor } from "@capacitor/core";
import type { AxiosRequestConfig } from "axios";

import { API_BASE_URL, apiClient } from "./client";

// Orval custom instance mutator (httpClient: "axios" mode)
// Wraps the existing apiClient so all interceptors (auth, community header) are preserved.
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
  // Orval 8.10 emits an explicit `Content-Type: multipart/form-data` for FormData
  // uploads. Axios's browser XHR adapter silently drops it so the transport can set
  // the value with the correct `; boundary=…`, but Node/Capacitor adapters may not,
  // which would send the header without a boundary and break server-side parsing.
  // Strip it here so every transport sets the boundary itself.
  if (merged.data instanceof FormData && merged.headers) {
    const headers = { ...merged.headers } as Record<string, unknown>;
    delete headers["Content-Type"];
    delete headers["content-type"];
    merged.headers = headers;
  }
  return apiClient<T>(merged).then(({ data }) => data);
};

export default apiMutator;

export type ErrorType<Error> = Error;
export type BodyType<BodyData> = BodyData;
