/**
 * Asking whoever runs this deployment for help.
 *
 * Whether a community takes help requests is a field on the guild the sidebar
 * already holds, so nothing here fetches it — the caller passes what it read.
 */

import type {
  SupportRequestAccepted,
  SupportRequestCreate,
} from "@/api/generated/initiativeAPI.schemas";
import { askForHelpApiV1GGuildIdSupportPost } from "@/api/generated/support/support";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

/** Where somebody is sent when this community takes no help requests. */
export const FAQ_URL = "https://morelitea.github.io/initiative/en/faq/";

export const useAskForHelp = (
  guildId: number,
  options?: MutationOpts<SupportRequestAccepted, SupportRequestCreate>
) =>
  useApiMutation<SupportRequestAccepted, SupportRequestCreate>(
    {
      // Nothing of the reader's is changed by asking, so nothing is invalidated:
      // the case lands in a project they have no part in.
      mutationFn: (body) => askForHelpApiV1GGuildIdSupportPost(guildId, body),
    },
    options
  );
