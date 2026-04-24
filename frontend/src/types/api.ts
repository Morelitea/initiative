/**
 * Convenience re-exports from the generated Orval schemas.
 *
 * Importing domain types from this file lets the rest of the app avoid
 * reaching into `@/api/generated/*` directly, which keeps swap-out churn
 * contained if Orval's layout ever changes.
 *
 * Add new re-exports here alongside the feature types they belong to.
 */

// ── Property definitions ────────────────────────────────────────────────────

export type {
  PropertyDefinitionCreate,
  PropertyDefinitionRead,
  PropertyDefinitionUpdate,
  PropertyDefinitionUpdateResponse,
  PropertyEntitiesResult,
  PropertyOption,
  PropertySummary,
  PropertyValueInput,
  PropertyValuesSetRequest,
} from "@/api/generated/initiativeAPI.schemas";

export { PropertyType } from "@/api/generated/initiativeAPI.schemas";
