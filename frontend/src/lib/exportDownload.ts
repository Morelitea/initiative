import { apiClient } from "@/api/client";
import { toast } from "@/lib/chesterToast";
import { downloadBlob } from "@/lib/csv";
import { getErrorMessage } from "@/lib/errorMessage";

/** Axios error bodies arrive as Blobs under responseType "blob"; recover the
 * JSON detail so getErrorMessage can map it to a localized message. */
export async function normalizeBlobError(err: unknown): Promise<unknown> {
  const response = (err as { response?: { data?: unknown } })?.response;
  if (response?.data instanceof Blob) {
    try {
      response.data = JSON.parse(await response.data.text());
    } catch {
      // keep the original error
    }
  }
  return err;
}

/** Fetch a finished export job's artifact and hand it to the browser as a
 * download. Shared by the export button and the notification bell — the loose
 * ``t`` shape (same as NotificationBell's helpers) admits any caller's bound
 * namespaces, since the toast keys here are namespace-prefixed. */
export async function downloadExportArtifact(
  guildId: number,
  jobId: number,
  t: (key: string, options?: Record<string, unknown>) => string,
  source = "tasks",
  format = "pdf"
): Promise<void> {
  try {
    const res = await apiClient.get<Blob>(`/g/${guildId}/exports/${jobId}/download`, {
      responseType: "blob",
    });
    downloadBlob(res.data, `${source}-${jobId}.${format}`);
    toast.success(t("tasks:export.success"));
  } catch (err) {
    toast.error(getErrorMessage(await normalizeBlobError(err), "tasks:export.error"));
  }
}
