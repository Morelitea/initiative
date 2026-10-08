import { ImageIcon, ImagePlus, Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { ImagePicker } from "@/components/ui/image-picker";
import { resolveUploadUrl } from "@/lib/uploadUrl";

interface FileFeaturedImageProps {
  url: string | null;
  canEdit: boolean;
  uploading: boolean;
  onUpload: (file: File) => void;
  onRemove: () => void;
}

/**
 * The picture a file leads with, and the one its card shows.
 *
 * Set, it runs the width of the file at its own shape, never cropped, and
 * no taller than most of the screen. Unset, a writer gets one small row
 * to add it from, there before a word is written; a reader sees nothing. A
 * picture written into the body can be made the featured one from the picture
 * itself, so this row is one of two ways in.
 */
export const FileFeaturedImage = ({
  url,
  canEdit,
  uploading,
  onUpload,
  onRemove,
}: FileFeaturedImageProps) => {
  const { t } = useTranslation("files");

  const upload = (label: string, variant: "secondary" | "ghost") => (
    <ImagePicker
      variant="button"
      buttonVariant={variant}
      buttonSize="sm"
      accept="image/*"
      disabled={uploading}
      onSelect={onUpload}
    >
      {uploading ? (
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      ) : (
        <ImagePlus className="h-4 w-4" aria-hidden />
      )}
      {uploading ? t("featuredImage.uploading") : label}
    </ImagePicker>
  );

  if (url) {
    return (
      <figure className="group relative overflow-hidden rounded-xl border bg-muted">
        <img
          src={resolveUploadUrl(url) ?? undefined}
          alt={t("featuredImage.label")}
          referrerPolicy="no-referrer"
          className="max-h-[60vh] w-full object-contain"
        />
        {canEdit ? (
          <div className="absolute top-2 right-2 flex gap-2 transition-opacity expanded:opacity-0 expanded:group-hover:opacity-100 expanded:group-focus-within:opacity-100">
            {upload(t("featuredImage.replace"), "secondary")}
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={onRemove}
              disabled={uploading}
            >
              <X className="h-4 w-4" aria-hidden />
              {t("featuredImage.remove")}
            </Button>
          </div>
        ) : null}
      </figure>
    );
  }

  if (!canEdit) return null;

  return (
    <div className="flex items-center gap-3">
      <div className="flex h-9 w-12 shrink-0 items-center justify-center rounded-md border border-dashed text-muted-foreground">
        <ImageIcon className="h-4 w-4" aria-hidden />
      </div>
      <span className="text-muted-foreground text-sm">{t("featuredImage.label")}</span>
      {upload(t("featuredImage.upload"), "ghost")}
    </div>
  );
};
