import { Download, ImagePlus, Loader2, Star, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  GalleryImageRead,
  GalleryImageVersionRead,
  TagSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { LazyImage } from "@/components/shared/LazyImage";
import { TagPicker } from "@/components/tags/TagPicker";
import { UserHandle } from "@/components/UserHandle";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { ImagePicker } from "@/components/ui/image-picker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RelativeTime } from "@/components/ui/relative-time";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import {
  useDeleteGalleryImage,
  useDeleteGalleryImageVersion,
  useGalleryImageVersions,
  useUpdateGalleryImage,
  useUploadGalleryImageVersion,
} from "@/hooks/useGalleries";
import { toast } from "@/lib/chesterToast";
import { formatBytes } from "@/lib/fileUtils";
import { ACCEPT_ATTRIBUTE, imageLabel, imageSrc, refuseFile } from "@/lib/galleries";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { cn } from "@/lib/utils";

interface GalleryImageSheetProps {
  galleryId: number;
  image: GalleryImageRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  canEdit: boolean;
  isOwner: boolean;
  isCover: boolean;
  onSetCover: (imageId: number) => void;
  onRemoved: (imageId: number) => void;
}

/**
 * Everything about one picture that is not the picture.
 *
 * A side panel rather than a page: a picture has no address of its own, and
 * its details are read beside the wall it is on. What somebody called it,
 * what they said about it, its tags, who put it there and when, how big it
 * is — and its history, where a design round is replaced rather than added
 * to and the earlier rounds are the story of how it got there.
 */
export const GalleryImageSheet = ({
  galleryId,
  image,
  open,
  onOpenChange,
  canEdit,
  isOwner,
  isCover,
  onSetCover,
  onRemoved,
}: GalleryImageSheetProps) => {
  const { t } = useTranslation(["galleries", "common"]);
  const imageId = image?.id ?? null;

  const [title, setTitle] = useState("");
  const [caption, setCaption] = useState("");
  const [tags, setTags] = useState<TagSummary[]>([]);
  // The form follows the picture, not the panel: opening a second picture in
  // the same panel starts from that picture's own words.
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset keyed on which picture is shown
  useEffect(() => {
    setTitle(image?.title ?? "");
    setCaption(image?.caption ?? "");
    setTags(image?.tags ?? []);
  }, [imageId]);

  const dirty =
    image !== null &&
    (title !== (image.title ?? "") ||
      caption !== (image.caption ?? "") ||
      tags.map((tag) => tag.id).join(",") !== image.tags.map((tag) => tag.id).join(","));

  const update = useUpdateGalleryImage(galleryId, {
    onSuccess: () => toast.success(t("sheet.saved")),
  });
  const versionsQuery = useGalleryImageVersions(galleryId, open ? imageId : null);
  const uploadVersion = useUploadGalleryImageVersion(galleryId, {
    onSuccess: () => toast.success(t("sheet.versionUploaded")),
  });
  const deleteVersion = useDeleteGalleryImageVersion(galleryId, {
    onSuccess: () => {
      setVersionPendingDelete(null);
      toast.success(t("sheet.versionDeleted"));
    },
  });
  const remove = useDeleteGalleryImage(galleryId, {
    onSuccess: (_, removedId) => {
      setConfirmRemove(false);
      onOpenChange(false);
      toast.success(t("sheet.removed"));
      onRemoved(removedId);
    },
  });
  const [versionPendingDelete, setVersionPendingDelete] = useState<GalleryImageVersionRead | null>(
    null
  );
  const [confirmRemove, setConfirmRemove] = useState(false);

  if (!image) return null;
  const label = imageLabel(image);
  const versions = versionsQuery.data ?? [];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 overflow-y-auto sm:max-w-md">
        <SheetHeader className="text-left">
          <SheetTitle className="truncate">{label || t("sheet.title")}</SheetTitle>
          <SheetDescription className="sr-only">{t("sheet.description")}</SheetDescription>
        </SheetHeader>

        <div className="space-y-6 py-4">
          <LazyImage
            src={imageSrc(image)}
            alt={label}
            aspectRatio={image.width && image.height ? image.width / image.height : 4 / 3}
            className="w-full rounded-lg"
            imgClassName="object-contain"
          />

          {/* What it is called, and what is said about it. */}
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="gallery-image-title">{t("sheet.titleLabel")}</Label>
              <Input
                id="gallery-image-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder={image.original_filename ?? t("sheet.titlePlaceholder")}
                maxLength={255}
                disabled={!canEdit}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="gallery-image-caption">{t("sheet.caption")}</Label>
              <Textarea
                id="gallery-image-caption"
                value={caption}
                onChange={(event) => setCaption(event.target.value)}
                placeholder={t("sheet.captionPlaceholder")}
                rows={3}
                maxLength={2000}
                disabled={!canEdit}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="gallery-image-tags">{t("sheet.tags")}</Label>
              <TagPicker
                id="gallery-image-tags"
                selectedTags={tags}
                onChange={setTags}
                disabled={!canEdit}
              />
            </div>
            {canEdit && dirty && (
              <div className="flex justify-end">
                <Button
                  size="sm"
                  disabled={update.isPending}
                  onClick={() =>
                    update.mutate({
                      imageId: image.id,
                      data: {
                        title: title.trim() || null,
                        caption: caption.trim() || null,
                        tag_ids: tags.map((tag) => tag.id),
                      },
                    })
                  }
                >
                  {update.isPending && <Loader2 className="size-4 animate-spin" />}
                  {t("common:save")}
                </Button>
              </div>
            )}
          </div>

          {/* Where it came from. */}
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
            <dt className="text-muted-foreground">{t("sheet.uploadedBy")}</dt>
            <dd className="flex min-w-0 items-center gap-2">
              {image.uploader ? (
                <>
                  <ProfileAvatar
                    user={image.uploader}
                    decorations={image.uploader.profile_decorations}
                    presence={image.uploader.presence}
                    className="size-5 shrink-0"
                  />
                  <UserHandle user={image.uploader} nameClassName="min-w-0 truncate" />
                </>
              ) : (
                "—"
              )}
            </dd>
            <dt className="text-muted-foreground">{t("sheet.added")}</dt>
            <dd>
              <RelativeTime date={image.created_at} />
            </dd>
            {image.width && image.height ? (
              <>
                <dt className="text-muted-foreground">{t("sheet.dimensions")}</dt>
                <dd className="tabular-nums">
                  {image.width} × {image.height}
                </dd>
              </>
            ) : null}
            {image.file_size ? (
              <>
                <dt className="text-muted-foreground">{t("sheet.size")}</dt>
                <dd>{formatBytes(image.file_size)}</dd>
              </>
            ) : null}
            {image.original_filename ? (
              <>
                <dt className="text-muted-foreground">{t("sheet.filename")}</dt>
                <dd className="truncate">{image.original_filename}</dd>
              </>
            ) : null}
          </dl>

          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" asChild>
              <a href={imageSrc(image)} download={image.original_filename ?? undefined}>
                <Download className="size-4" />
                {t("sheet.download")}
              </a>
            </Button>
            {canEdit && (
              <Button
                variant="outline"
                size="sm"
                disabled={isCover}
                onClick={() => onSetCover(image.id)}
              >
                <Star className={cn("size-4", isCover && "fill-current")} />
                {isCover ? t("sheet.isCover") : t("sheet.setCover")}
              </Button>
            )}
            {canEdit && (
              <Button
                variant="outline"
                size="sm"
                className="text-destructive"
                onClick={() => setConfirmRemove(true)}
              >
                <Trash2 className="size-4" />
                {t("sheet.remove")}
              </Button>
            )}
          </div>

          {/* The history. */}
          <section className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-medium text-sm">{t("sheet.versions")}</h3>
              {canEdit && (
                <ImagePicker
                  variant="button"
                  buttonSize="sm"
                  accept={ACCEPT_ATTRIBUTE}
                  disabled={uploadVersion.isPending}
                  onSelect={(file) => {
                    if (refuseFile(file)) {
                      toast.error(t("upload.refusedType"));
                      return;
                    }
                    uploadVersion.mutate({ imageId: image.id, file });
                  }}
                >
                  {uploadVersion.isPending ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <ImagePlus className="size-4" />
                  )}
                  {t("sheet.uploadVersion")}
                </ImagePicker>
              )}
            </div>
            <ul className="divide-y rounded-md border">
              {versions.map((version) => (
                <li key={version.id} className="flex items-center gap-3 p-2 text-sm">
                  <LazyImage
                    src={resolveUploadUrl(version.thumbnail_url ?? version.file_url)}
                    alt=""
                    className="size-12 shrink-0 rounded"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate">
                      {t("sheet.versionLabel", { number: version.version_number })}
                      {version.is_current && (
                        <span className="ml-2 text-muted-foreground text-xs">
                          {t("sheet.current")}
                        </span>
                      )}
                    </p>
                    <p className="text-muted-foreground text-xs">
                      <RelativeTime date={version.created_at} />
                      {version.file_size ? ` · ${formatBytes(version.file_size)}` : ""}
                    </p>
                  </div>
                  {isOwner && versions.length > 1 && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-8 text-muted-foreground hover:text-destructive"
                      aria-label={t("sheet.deleteVersion")}
                      onClick={() => setVersionPendingDelete(version)}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </section>
        </div>

        <ConfirmDialog
          open={versionPendingDelete !== null}
          onOpenChange={(next) => !next && setVersionPendingDelete(null)}
          title={t("sheet.deleteVersionTitle")}
          description={t("sheet.deleteVersionDescription", {
            number: versionPendingDelete?.version_number ?? 0,
          })}
          confirmLabel={t("common:delete")}
          cancelLabel={t("common:cancel")}
          isLoading={deleteVersion.isPending}
          destructive
          onConfirm={() => {
            if (versionPendingDelete) {
              deleteVersion.mutate({ imageId: image.id, versionId: versionPendingDelete.id });
            }
          }}
        />
        <ConfirmDialog
          open={confirmRemove}
          onOpenChange={setConfirmRemove}
          title={t("sheet.removeTitle")}
          description={t("sheet.removeDescription")}
          confirmLabel={t("sheet.remove")}
          cancelLabel={t("common:cancel")}
          isLoading={remove.isPending}
          destructive
          onConfirm={() => remove.mutate(image.id)}
        />
      </SheetContent>
    </Sheet>
  );
};
