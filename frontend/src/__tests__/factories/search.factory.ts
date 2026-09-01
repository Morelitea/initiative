import type {
  SearchHit,
  SearchResults,
  SearchSuggestion,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

/**
 * One thing found. Defaults to a project — a tool's own row, the simplest
 * shape — so a test overriding `entity_type` states only what it is varying.
 * A child entity names its parent through `tool`/`tool_id`.
 */
export function buildSearchHit(overrides: Partial<SearchHit> = {}): SearchHit {
  counter++;
  return {
    entity_type: "project",
    entity_id: counter,
    title: `Search Hit ${counter}`,
    snippet: null,
    initiative_id: 5,
    tool: Tool.project,
    tool_id: counter,
    ...overrides,
  };
}

/** A palette suggestion: a hit without the snippet, which the palette has no
 *  room to show. */
export function buildSearchSuggestion(overrides: Partial<SearchSuggestion> = {}): SearchSuggestion {
  const hit = buildSearchHit(overrides);
  return {
    entity_type: hit.entity_type,
    entity_id: hit.entity_id,
    title: hit.title,
    initiative_id: hit.initiative_id,
    tool: hit.tool,
    tool_id: hit.tool_id,
  };
}

/**
 * A page of results. `total` counts everything that matched, not what is on
 * this page — pass it to describe an answer that runs past one page.
 */
export function buildSearchResults(
  items: SearchHit[] = [],
  overrides: Partial<SearchResults> = {}
): SearchResults {
  return { items, total: items.length, limit: 20, offset: 0, ...overrides };
}
