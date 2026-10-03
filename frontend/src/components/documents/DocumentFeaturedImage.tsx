import { ImagePlus, Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { ImagePicker } from "@/components/ui/image-picker";
import { resolveUploadUrl } from "@/lib/uploadUrl";

interface DocumentFeaturedImageProps {
  url: string | null;
  canEdit: boolean;
  uploading: boolean;
  /** Offer to add one: a writer looking at a document with nothing in it yet. */
  offerUpload: boolean;
  onUpload: (file: File) => void;
  onRemove: () => void;
  onDismiss: () => void;
}

/**
 * The picture a document leads with, and the one its card shows.
 *
 * Shown where there is one. Where there is not, a writer starting an empty
 * document is offered one, and can wave the offer away; a document that
 * already has words and no picture shows nothing, since any picture written
 * into it can be made the featured one from the picture itself.
 */
export const DocumentFeaturedImage = ({
  url,
  canEdit,
  uploading,
  offerUpload,
  onUpload,
  onRemove,
  onDismiss,
}: DocumentFeaturedImageProps) => {
  const { t } = useTranslation("documents");

  if (url) {
    return (
      <figure className="group relative overflow-hidden rounded-xl border bg-muted">
        <img
          src={resolveUploadUrl(url) ?? undefined}
          alt={t("featuredImage.label")}
          referrerPolicy="no-referrer"
          className="aspect-[3/1] w-full object-cover"
        />
        {canEdit ? (
          <div className="absolute top-2 right-2 flex gap-2 transition-opacity md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100">
            <ImagePicker
              variant="button"
              buttonVariant="secondary"
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
              {uploading ? t("featuredImage.uploading") : t("featuredImage.replace")}
            </ImagePicker>
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

  if (!canEdit || !offerUpload) return null;

  return (
    <div className="relative flex flex-col items-start gap-3 rounded-xl border border-dashed p-4 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1 pr-8 sm:pr-0">
        <p className="font-medium text-sm">{t("featuredImage.add")}</p>
        <p className="text-muted-foreground text-sm">{t("featuredImage.addHint")}</p>
      </div>
      <ImagePicker
        variant="button"
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
        {uploading ? t("featuredImage.uploading") : t("featuredImage.upload")}
      </ImagePicker>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="absolute top-2 right-2 h-7 w-7 sm:static"
        onClick={onDismiss}
        aria-label={t("featuredImage.dismiss")}
      >
        <X className="h-4 w-4" aria-hidden />
      </Button>
    </div>
  );
};
