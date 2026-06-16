import { uploadAttachmentApiV1GGuildIdAttachmentsPost } from "@/api/generated/attachments/attachments";
import type { AttachmentUploadResponse } from "@/api/generated/initiativeAPI.schemas";

export const uploadAttachment = async (
  guildId: number,
  file: File
): Promise<AttachmentUploadResponse> => {
  return uploadAttachmentApiV1GGuildIdAttachmentsPost(guildId, {
    file,
  }) as unknown as Promise<AttachmentUploadResponse>;
};
