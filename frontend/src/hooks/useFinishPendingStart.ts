import { useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { type CommunityCategory, Tool } from "@/api/generated/initiativeAPI.schemas";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import { toast } from "@/lib/chesterToast";
import { communityPath } from "@/lib/communityUrl";
import {
  clearStart,
  findStartedCommunity,
  readPendingStart,
  type StartAnswers,
  type Starter,
  seedStarter,
} from "@/lib/startFlow";
import { toolDetailRoute } from "@/lib/tools";

/** Where a finished start lands: Personal on its list, anything else on the
 *  community's home. */
export const useLandOnStarter = () => {
  const navigate = useNavigate();
  return useCallback(
    async (communityId: number, starter: Starter | null) => {
      await navigate({
        to: communityPath(
          communityId,
          starter?.projectId
            ? toolDetailRoute(Tool.project, starter.initiativeId, starter.projectId)
            : "/"
        ),
      });
    },
    [navigate]
  );
};

/** The directory, on the shelves they picked. */
export const useOpenDirectory = () => {
  const navigate = useNavigate();
  return useCallback(
    (categories: CommunityCategory[]) =>
      navigate({
        to: "/communities",
        search: categories.length ? { category: categories } : {},
      }),
    [navigate]
  );
};

/** Make the starter content, saying so if it could not be made. */
export const useSeedStarter = () => {
  const { t } = useTranslation("auth");
  return useCallback(
    async (communityId: number, answers: StartAnswers): Promise<Starter | null> => {
      try {
        return await seedStarter(communityId, answers);
      } catch {
        toast.error(t("start.starterError"));
        return null;
      }
    },
    [t]
  );
};

/**
 * Finish a start that signed up on this browser but could not sign in then,
 * on the first load that is signed in as that account.
 */
export const useFinishPendingStart = (): void => {
  const { user } = useAuth();
  const { communities, loading, refreshCommunities } = useCommunities();
  const seed = useSeedStarter();
  const landOn = useLandOnStarter();
  const openDirectory = useOpenDirectory();
  const done = useRef(false);
  const refetched = useRef(false);

  useEffect(() => {
    if (done.current || !user?.email || loading) return;
    const answers = readPendingStart(user.email);
    if (!answers) return;
    if (answers.path === "join" || answers.path === "invite") {
      done.current = true;
      void (async () => {
        await clearStart();
        if (answers.path === "join" && !user.age_below_minimum_at) {
          await openDirectory(answers.categories);
        }
      })();
      return;
    }
    // Kept until the new community is in the list; a list read before it
    // existed is read once more.
    const community = findStartedCommunity(communities, answers);
    if (!community) {
      if (!refetched.current) {
        refetched.current = true;
        void refreshCommunities().catch(() => undefined);
      }
      return;
    }
    done.current = true;
    void (async () => {
      await clearStart();
      await landOn(community.id, await seed(community.id, answers));
    })();
  }, [user, loading, communities, refreshCommunities, seed, landOn, openDirectory]);
};
