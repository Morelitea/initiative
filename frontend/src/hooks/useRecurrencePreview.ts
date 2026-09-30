import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type { RecurrencePreviewRequest } from "@/api/generated/initiativeAPI.schemas";
import { previewRecurrenceApiV1RecurrencePreviewPost } from "@/api/generated/recurrence/recurrence";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";

/**
 * A repeat's next starts, from the engine the calendar uses, asked once the
 * form stops changing. `null` asks nothing. A rule the server refuses shows
 * no dates rather than an error: the form says what is wrong with it.
 */
export const useRecurrencePreview = (request: RecurrencePreviewRequest | null) => {
  // Debounced as a string: a request object is new on every render.
  const key = useDebouncedValue(request ? JSON.stringify(request) : null, 300);
  return useQuery({
    queryKey: ["recurrence-preview", key],
    queryFn: () =>
      previewRecurrenceApiV1RecurrencePreviewPost(
        JSON.parse(key as string) as RecurrencePreviewRequest
      ),
    enabled: key !== null,
    placeholderData: keepPreviousData,
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });
};
