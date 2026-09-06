import { useParams } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolSettingsLayout } from "@/components/tools/settings/ToolSettingsLayout";
import { useDeletePost, usePost, useSetPostGrants, useUpdatePost } from "@/hooks/usePosts";

export const PostSettingsPage = () => {
  const { postId } = useParams({ strict: false }) as { postId?: string };
  const parsedId = postId ? Number(postId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);

  const postQuery = usePost(isValidId ? parsedId : null);
  const update = useUpdatePost(parsedId);
  const setGrants = useSetPostGrants(parsedId);
  const remove = useDeletePost();

  return (
    <ToolSettingsLayout
      tool={Tool.post}
      entity={postQuery.data}
      isLoading={isValidId && postQuery.isLoading}
      isError={!isValidId || postQuery.isError}
      update={update}
      setGrants={setGrants}
      remove={remove}
    />
  );
};
