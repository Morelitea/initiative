/**
 * What a suspended account is told on its time-out screen: why, where a reason
 * was given, and whom to contact. Readable while suspended, which almost
 * nothing else is.
 */

import { useQuery } from "@tanstack/react-query";

import type { AccountTimeOutRead } from "@/api/generated/initiativeAPI.schemas";
import {
  getReadMyTimeOutApiV1UsersMeTimeOutGetQueryKey,
  readMyTimeOutApiV1UsersMeTimeOutGet,
} from "@/api/generated/users/users";
import type { QueryOpts } from "@/types/query";

export const useAccountTimeOut = (options?: QueryOpts<AccountTimeOutRead>) =>
  useQuery<AccountTimeOutRead>({
    queryKey: getReadMyTimeOutApiV1UsersMeTimeOutGetQueryKey(),
    queryFn: () => readMyTimeOutApiV1UsersMeTimeOutGet(),
    ...options,
  });
