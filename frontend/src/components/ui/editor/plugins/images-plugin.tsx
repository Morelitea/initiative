import { createCommand, type LexicalCommand, type LexicalEditor } from "lexical";
import { type JSX, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { DialogFooter } from "@/components/ui/dialog";
import { useFeaturedImage } from "@/components/ui/editor/context/featured-image-context";
import type { ImagePayload } from "@/components/ui/editor/nodes/image-node";
import { ImagePicker } from "@/components/ui/image-picker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsBar, TabsContent, TabsTrigger } from "@/components/ui/tabs";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { uploadAttachment } from "@/lib/attachmentUtils";

export type InsertImagePayload = Readonly<ImagePayload>;

export const INSERT_IMAGE_COMMAND: LexicalCommand<InsertImagePayload> =
  createCommand("INSERT_IMAGE_COMMAND");

export function InsertImageUriDialogBody({
  onClick,
}: {
  onClick: (payload: InsertImagePayload) => void;
}) {
  const [src, setSrc] = useState("");
  const [altText, setAltText] = useState("");

  const isDisabled = src === "";

  return (
    <div className="grid gap-4 py-4">
      <div className="grid gap-2">
        <Label htmlFor="image-url">Image URL</Label>
        <Input
          id="image-url"
          placeholder="i.e. https://source.unsplash.com/random"
          onChange={(e) => setSrc(e.target.value)}
          value={src}
          data-test-id="image-modal-url-input"
        />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="alt-text">Alt Text</Label>
        <Input
          id="alt-text"
          placeholder="Random unsplash image"
          onChange={(e) => setAltText(e.target.value)}
          value={altText}
          data-test-id="image-modal-alt-text-input"
        />
      </div>
      <DialogFooter>
        <Button
          type="submit"
          disabled={isDisabled}
          onClick={() => onClick({ altText, src })}
          data-test-id="image-modal-confirm-btn"
        >
          Confirm
        </Button>
      </DialogFooter>
    </div>
  );
}

export function InsertImageUploadedDialogBody({
  onClick,
}: {
  onClick: (payload: InsertImagePayload) => void;
}) {
  const { t } = useTranslation("editor");
  const communityId = useActiveCommunityId();
  const featured = useFeaturedImage();
  const featuredId = useId();
  const [src, setSrc] = useState("");
  const [altText, setAltText] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [fileName, setFileName] = useState("");
  const [makeFeatured, setMakeFeatured] = useState(false);

  const isDisabled = src === "" || isUploading;

  const handleFileChange = async (file: File) => {
    setFileName(file.name);
    setAltText(file.name);
    setIsUploading(true);

    try {
      const response = await uploadAttachment(communityId, file);
      setSrc(response.url);
    } catch (error) {
      console.error("Failed to upload image:", error);
      setSrc("");
      setFileName("");
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="grid gap-4 py-4">
      <div className="grid gap-2">
        <Label htmlFor="image-upload">Image Upload</Label>
        <ImagePicker
          id="image-upload"
          onSelect={(file) => handleFileChange(file)}
          accept="image/*"
          disabled={isUploading}
          data-test-id="image-modal-file-upload"
        />
        {isUploading && <p className="text-muted-foreground text-sm">Uploading {fileName}...</p>}
      </div>
      <div className="grid gap-2">
        <Label htmlFor="alt-text">Alt Text</Label>
        <Input
          id="alt-text"
          placeholder="Descriptive alternative text"
          onChange={(e) => setAltText(e.target.value)}
          value={altText}
          data-test-id="image-modal-alt-text-input"
        />
      </div>
      {featured ? (
        <div className="flex items-center gap-2">
          <Checkbox
            id={featuredId}
            checked={makeFeatured}
            onCheckedChange={(checked) => setMakeFeatured(checked === true)}
          />
          <Label htmlFor={featuredId}>{t("featuredImage.makeFeatured")}</Label>
        </div>
      ) : null}
      <Button
        type="submit"
        disabled={isDisabled}
        onClick={() => {
          if (makeFeatured) featured?.set(src);
          onClick({ altText, src });
        }}
        data-test-id="image-modal-file-upload-btn"
      >
        {isUploading ? "Uploading..." : "Confirm"}
      </Button>
    </div>
  );
}

export function InsertImageDialog({
  activeEditor,
  onClose,
}: {
  activeEditor: LexicalEditor;
  onClose: () => void;
}): JSX.Element {
  const hasModifier = useRef(false);

  useEffect(() => {
    hasModifier.current = false;
    const handler = (e: KeyboardEvent) => {
      hasModifier.current = e.altKey;
    };
    document.addEventListener("keydown", handler);
    return () => {
      document.removeEventListener("keydown", handler);
    };
  }, [activeEditor]);

  const onClick = (payload: InsertImagePayload) => {
    activeEditor.dispatchCommand(INSERT_IMAGE_COMMAND, payload);
    onClose();
  };

  return (
    <Tabs defaultValue="url">
      <TabsBar>
        <TabsTrigger value="url">URL</TabsTrigger>
        <TabsTrigger value="file">File</TabsTrigger>
      </TabsBar>
      <TabsContent value="url">
        <InsertImageUriDialogBody onClick={onClick} />
      </TabsContent>
      <TabsContent value="file">
        <InsertImageUploadedDialogBody onClick={onClick} />
      </TabsContent>
    </Tabs>
  );
}

declare global {
  interface DragEvent {
    rangeOffset?: number;
    rangeParent?: Node;
  }
}
