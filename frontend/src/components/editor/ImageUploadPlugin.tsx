import { useCallback, useEffect } from "react";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { COMMAND_PRIORITY_LOW, DROP_COMMAND, type PasteCommandType, PASTE_COMMAND } from "lexical";
import { toast } from "sonner";

import { uploadAttachment } from "@/api/attachments";
import { insertImageNode } from "@/components/editor/nodes/ImageNode";

type ImageUploadPluginProps = {
  disabled?: boolean;
};

const toFileArray = (fileList: FileList | File[]) =>
  Array.isArray(fileList) ? fileList : Array.from(fileList);

const filterImageFiles = (fileList: FileList | File[]) =>
  toFileArray(fileList).filter((file) => file.type.startsWith("image/"));

const hasImageFile = (fileList: FileList | File[]) => filterImageFiles(fileList).length > 0;

const hasClipboardData = (event: PasteCommandType): event is ClipboardEvent =>
  "clipboardData" in event && event.clipboardData !== undefined && event.clipboardData !== null;

export const ImageUploadPlugin = ({ disabled }: ImageUploadPluginProps) => {
  const [editor] = useLexicalComposerContext();

  const handleFiles = useCallback(
    async (fileList: FileList | File[]) => {
      const files = filterImageFiles(fileList);
      if (!files.length) {
        return;
      }
      for (const file of files) {
        try {
          const response = await uploadAttachment(file);
          insertImageNode(editor, { src: response.url, altText: file.name });
        } catch (error) {
          console.error(error);
          toast.error(`Failed to upload ${file.name}.`);
        }
      }
    },
    [editor]
  );

  useEffect(() => {
    if (disabled) {
      return undefined;
    }
    return editor.registerCommand(
      DROP_COMMAND,
      (event: DragEvent) => {
        const files = event.dataTransfer?.files;
        if (!files || files.length === 0) {
          return false;
        }
        if (!hasImageFile(files)) {
          return false;
        }
        event.preventDefault();
        void handleFiles(files);
        return true;
      },
      COMMAND_PRIORITY_LOW
    );
  }, [disabled, editor, handleFiles]);

  useEffect(() => {
    if (disabled) {
      return undefined;
    }
    return editor.registerCommand(
      PASTE_COMMAND,
      (event: PasteCommandType) => {
        if (!hasClipboardData(event)) {
          return false;
        }
        const clipboardData = event.clipboardData;
        if (!clipboardData) {
          return false;
        }
        const files = clipboardData.files;
        if (!files || files.length === 0) {
          return false;
        }
        if (!hasImageFile(files)) {
          return false;
        }
        event.preventDefault();
        void handleFiles(files);
        return true;
      },
      COMMAND_PRIORITY_LOW
    );
  }, [disabled, editor, handleFiles]);

  return null;
};
