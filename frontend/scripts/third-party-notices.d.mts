// Types for vite.config.ts, which imports the generator; see the .mjs beside it.
export interface NoticeCounts {
  packages: number;
  licences: number;
  fallbacks: number;
  plugins: number;
  nativeLibraries: number;
  fonts: number;
}

export function buildNotices(options?: { frontendDir?: string; bundleFiles?: string[] | null }): {
  text: string;
  counts: NoticeCounts;
};
