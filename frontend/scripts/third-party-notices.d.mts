// Types for vite.config.ts, which imports the generator; see the .mjs beside it.
export interface NoticeCounts {
  packages: number;
  nativeLibraries: number;
  fonts: number;
  plugins: number;
  standardLicences: number;
  standard: number;
  other: number;
  otherPackages: number;
  proprietary: number;
  supplied: number;
}

export function buildNotices(options?: { frontendDir?: string; bundleFiles?: string[] | null }): {
  text: string;
  counts: NoticeCounts;
};
