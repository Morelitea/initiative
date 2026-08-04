import type { UseMutationResult } from "@tanstack/react-query";

import type {
  AIConnectionCreate,
  AIConnectionResponse,
  AIConnectionTestResponse,
  AIConnectionUpdate,
  AIModelsResponse,
} from "@/api/generated/initiativeAPI.schemas";

/**
 * The mutations a connection manager drives. Platform and guild scopes share
 * this shape — only the underlying endpoints (and their guild binding) differ,
 * so both `SettingsAIPage` and `SettingsGuildAIPage` build one of these from
 * their scope-specific hooks and hand it to the shared UI.
 */
export interface ConnectionMutations {
  create: UseMutationResult<AIConnectionResponse, Error, AIConnectionCreate, unknown>;
  update: UseMutationResult<
    AIConnectionResponse,
    Error,
    { connectionId: number; data: AIConnectionUpdate },
    unknown
  >;
  remove: UseMutationResult<void, Error, number, unknown>;
  test: UseMutationResult<AIConnectionTestResponse, Error, number, unknown>;
  fetchModels: UseMutationResult<AIModelsResponse, Error, number, unknown>;
}
