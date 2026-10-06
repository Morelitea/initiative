import { createFileRoute } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { PostReactionsField } from "@/components/initiativeTools/posts/PostReactionsField";
import { ToolSettingsPage } from "@/pages/toolSettings/ToolSettingsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/posts/$postId/settings"
)({
  component: () => <ToolSettingsPage tool={Tool.post} detailsInline={<PostReactionsField />} />,
});
