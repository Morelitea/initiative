import { uploadAttachmentApiV1AttachmentsPost } from "@/api/generated/attachments/attachments";
import type { AttachmentUploadResponse } from "@/types/api";

export const uploadAttachment = async (file: File): Promise<AttachmentUploadResponse> => {
  return uploadAttachmentApiV1AttachmentsPost({
    file,
  }) as unknown as Promise<AttachmentUploadResponse>;
};
