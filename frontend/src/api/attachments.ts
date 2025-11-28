import type { AttachmentUploadResponse } from "@/types/api";
import { apiClient } from "@/api/client";

export const uploadAttachment = async (file: File): Promise<AttachmentUploadResponse> => {
  const formData = new FormData();
  formData.append("file", file);

  const response = await apiClient.post<AttachmentUploadResponse>("/attachments/", formData, {
    headers: {
      "Content-Type": "multipart/form-data",
    },
  });
  return response.data;
};
