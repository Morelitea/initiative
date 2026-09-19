/**
 * Reporting something.
 *
 * One call from every surface. Where it goes is the server's decision — a
 * community's own content reaches that community's moderators, and anything
 * about an account or a community reaches whoever runs the deployment — so
 * nothing here branches on what is being reported.
 */

import type { ReportAccepted, ReportCreate } from "@/api/generated/initiativeAPI.schemas";
import { fileReportApiV1MeReportsPost } from "@/api/generated/moderation/moderation";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

export const useFileReport = (options?: MutationOpts<ReportAccepted, ReportCreate>) =>
  useApiMutation<ReportAccepted, ReportCreate>(
    {
      mutationFn: (body) => fileReportApiV1MeReportsPost(body),
      // Nothing to invalidate: a reporter never sees what they filed, and the
      // moderators who do are not this reader.
    },
    options
  );
