import {
  discardPastedImage as discardPastedImageRequest,
  uploadAttachment as uploadAttachmentRequest,
  uploadPastedImage as uploadPastedImageRequest,
} from "@/api/generated/attachments/attachments";
import type { AttachmentUploadResponse } from "@/api/generated/initiativeAPI.schemas";

export const uploadAttachment = async (
  guildId: number,
  file: File
): Promise<AttachmentUploadResponse> => {
  return uploadAttachmentRequest(guildId, {
    file,
  }) as unknown as Promise<AttachmentUploadResponse>;
};

/** A picture pasted into markdown — a task's description, a comment — stored
 *  so that taking it back out, or purging what it is in, deletes it. */
export const uploadPastedImage = async (guildId: number, file: File): Promise<string> => {
  const response = (await uploadPastedImageRequest(guildId, {
    file,
  })) as unknown as AttachmentUploadResponse;
  return response.url;
};

/** Ask for a pasted picture to be thrown away. The server keeps it if anything
 *  saved shows it, or if somebody else uploaded it. */
export const discardPastedImage = async (guildId: number, url: string): Promise<void> => {
  const filename = url.split("/").pop();
  if (!filename) return;
  await discardPastedImageRequest(guildId, filename);
};
