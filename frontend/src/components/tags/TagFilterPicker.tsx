import { useMemo } from "react";

import type { TagRead } from "@/api/generated/initiativeAPI.schemas";
import { useTags } from "@/hooks/useTags";

import { TagPicker } from "./TagPicker";

interface TagFilterPickerProps {
  id?: string;
  /** The tags to narrow by, as a list's `tag_ids` carries them. */
  tagIds: number[];
  onChange: (tagIds: number[]) => void;
  placeholder?: string;
}

/** A tag filter over tag ids, shown with the community's own tags. */
export function TagFilterPicker({ id, tagIds, onChange, placeholder }: TagFilterPickerProps) {
  const { data: allTags = [] } = useTags();
  const selectedTags = useMemo(() => {
    const byId = new Map(allTags.map((tag) => [tag.id, tag]));
    return tagIds.map((tagId) => byId.get(tagId)).filter((tag): tag is TagRead => tag != null);
  }, [allTags, tagIds]);

  return (
    <TagPicker
      id={id}
      variant="filter"
      selectedTags={selectedTags}
      onChange={(tags) => onChange(tags.map((tag) => tag.id))}
      placeholder={placeholder}
    />
  );
}
