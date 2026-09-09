/**
 * Resolve a widget's binding into the data envelope it renders from.
 *
 * The security shape of this file matters more than its size. A binding names a
 * *source*, never an endpoint — and each is fetched here through the same
 * ordinary hook the rest of the app uses, so the request is the viewer's own and
 * the six gates decide what comes back. A dashboard shared with someone who
 * cannot read the bound rows therefore shows them an empty widget, not the
 * author's data. Nothing a definition can say reaches a URL.
 *
 * Three bindings, and two of them answer with the same envelope: a statement
 * and a spreadsheet range are both columns and rows. Every hook below is called
 * on every render with `enabled` gating rather than conditionally, because
 * hooks must be unconditional. Disabled queries cost nothing, and the ones that
 * do run share React Query's cache — two widgets running the same statement
 * issue one request between them, which is what keeps a dense canvas from
 * becoming a request storm.
 */

import { useCallback, useMemo } from "react";

import { resolveAppBinding } from "@/api/appData";
import { useAppData, useAppWidgetCatalog } from "@/hooks/useAppData";
import { useDocument } from "@/hooks/useDocuments";
import { useSqlQuery } from "@/hooks/useSqlQuery";
import type { DataMeta, WidgetData, WidgetSource } from "@/lib/widgets/dataShapes";
import { WidgetErrorCode } from "@/lib/widgets/errors";
import { emptyDataFor, normalizeQueryRows, normalizeSheetRange } from "@/lib/widgets/normalize";

/** A normalized definition binding. Everything past `source` is the fetcher's
 *  to interpret — the backend deliberately does not re-declare these, so that
 *  each parameter lives with the code that consumes it.
 *
 *  The initiative is *not* among them: it comes from the dashboard the widget
 *  sits on, and the backend normalizer drops it from a stored binding. */
export interface WidgetBinding {
  source: WidgetSource;
  /** `query`: the statement to read. Checked and rewritten by the server before
   *  it runs — what is stored is what the author built, and what reaches
   *  Postgres is what the validator produced from it. */
  sql?: string | null;
  /** What was clicked to produce `sql`, so the builder reopens on it rather
   *  than leaving somebody to read their own statement back. Absent for a
   *  statement that did not come from the builder. */
  spec?: unknown;
  document_id?: number | null;
  sheet?: string | null;
  range?: string | null;
  /** `app`: which installed app, which of its sources, and the arguments the
   *  source declared. The binding names a listing and a source id — never an
   *  address. Where the app lives comes from the deployment's registration, and
   *  only the server ever reads it. */
  app_uid?: string | null;
  endpoint_id?: string | null;
  params?: Record<string, unknown> | null;
}

export interface WidgetDataResult {
  data: WidgetData;
  /** A binding whose parameters the instance config has not filled in yet — the
   *  widget renders its own empty state rather than an error. */
  isUnbound: boolean;
  isLoading: boolean;
  /** The binding names a target, the fetch resolved, and the target is not
   *  there: deleted, or hidden from this viewer by the gates.
   *
   *  Deliberately distinct from {@link isUnbound}. They are opposite
   *  instructions — one asks the author to finish configuring a widget, the
   *  other says this viewer is not the person who can see the answer — and
   *  telling a reader to "configure this" invites them to repoint a binding
   *  that was never wrong. What the tile may *say* about it is bounded:
   *  absence, never the name or id of the thing that is absent. */
  isRestricted: boolean;
  /** Rows this viewer's own query matched, and whether the rows in `data` are a
   *  leading slice of them. Mirrors `data.meta`, hoisted for the tile chrome. */
  meta?: DataMeta;
  /** Re-run this binding's own queries. Lives here because this is the only
   *  place that knows which ones a source uses. */
  refetch: () => void;
  /** Set when the tile should draw an error instead of running the widget. */
  errorCode?: WidgetErrorCode;
}

/**
 * Resolve one widget's binding.
 *
 * `initiativeId` is the dashboard's own — every fetch below is scoped to it, and
 * a binding cannot say otherwise: dashboards are an initiative's tool, so a
 * widget reads that initiative and nothing else. Without an initiative nothing
 * is fetched at all (unbound, not guild-wide), and a document fetched by id is
 * held against the initiative afterwards, so an id pointing into another one
 * resolves to absent — the same rendering as a deleted or unshared target.
 *
 * A statement needs no such holding: it runs under the reader's own session
 * against their guild's schema, and the policies on the tables it reads decide
 * every row it returns.
 *
 * `dashboardId` is the row the widget sits on, and only the `app` source needs
 * it: an app's data is guild-level, so the proxy is told which
 * initiative-scoped surface is asking and decides the read against *that* row's
 * gates.
 */
export function useWidgetData(
  binding: WidgetBinding,
  initiativeId: number | undefined,
  dashboardId?: number
): WidgetDataResult {
  const source = binding.source;
  const scoped = typeof initiativeId === "number" && Number.isFinite(initiativeId);

  // The statement is the request: no ids to resolve first, and nothing to
  // narrow it by afterwards — a query says what it reads.
  const sqlQuery = useSqlQuery(source === "query" ? (binding.sql ?? null) : null, {
    enabled: scoped && source === "query",
  });
  const documentQuery = useDocument(
    scoped && source === "sheet_range" ? (binding.document_id ?? null) : null
  );

  // The app palette is one request per guild, shared by every app widget on the
  // canvas. It is what turns a binding's `app_uid` into an install id and tells
  // us what freshness the source asks for.
  const isApp = source === "app";
  const appCatalogQuery = useAppWidgetCatalog(scoped && isApp);
  const appBinding = resolveAppBinding(appCatalogQuery.data, binding.app_uid, binding.endpoint_id);
  const appQuery = useAppData({
    appId: appBinding?.entry.app_id,
    endpointId: binding.endpoint_id ?? undefined,
    dashboardId,
    params: binding.params ?? undefined,
    cacheTtlSeconds: appBinding?.source.cache_ttl_seconds,
    enabled: scoped && isApp,
  });

  const refetch = useCallback(() => {
    if (source === "query") void sqlQuery.refetch();
    if (source === "sheet_range") void documentQuery.refetch();
    if (isApp) void appQuery.refetch();
  }, [source, isApp, sqlQuery.refetch, documentQuery.refetch, appQuery.refetch]);

  return useMemo<WidgetDataResult>(() => {
    const unbound = (): WidgetDataResult => ({
      data: emptyDataFor(source),
      isLoading: false,
      isUnbound: true,
      isRestricted: false,
      refetch,
    });

    /**
     * The binding named a target and the fetch came back without it.
     *
     * Three outcomes, and they must not be collapsed: still in flight; the
     * request failed, which says nothing at all about what this viewer may
     * see; or it succeeded and the target genuinely is not there for them.
     * Only the third is an access outcome, and only it says so.
     */
    const absent = (query: { isLoading: boolean; isError: boolean }): WidgetDataResult => ({
      data: emptyDataFor(source),
      isLoading: query.isLoading,
      isUnbound: false,
      isRestricted: !query.isLoading && !query.isError,
      errorCode: query.isError ? WidgetErrorCode.DATA_UNAVAILABLE : undefined,
      refetch,
    });

    // No initiative, no data — fail closed rather than fan out.
    if (!scoped) return unbound();

    switch (source) {
      case "query": {
        if (!binding.sql) return unbound();
        // A statement the server would not run — a name the registry does not
        // have, a shape this surface does not accept, a cost ceiling — is the
        // author's to fix rather than this viewer's, so it reads as an error
        // and not as absence. Rows this viewer may not see are simply not
        // returned: the statement runs under their own session.
        if (sqlQuery.isError) {
          return {
            data: emptyDataFor(source),
            isLoading: false,
            isUnbound: false,
            isRestricted: false,
            errorCode: WidgetErrorCode.DATA_UNAVAILABLE,
            refetch,
          };
        }
        const answered = sqlQuery.data;
        const { columns, rows } = normalizeQueryRows(answered?.columns ?? [], answered?.rows ?? []);
        const meta: DataMeta = { total: rows.length, truncated: Boolean(answered?.truncated) };
        return {
          data: { source: "rows", columns, rows, meta },
          isLoading: sqlQuery.isLoading,
          isUnbound: false,
          isRestricted: false,
          refetch,
          meta,
        };
      }

      case "sheet_range": {
        if (!binding.document_id || !binding.range) return unbound();
        // A document outside this initiative is absent, not readable.
        const document =
          documentQuery.data?.initiative_id === initiativeId ? documentQuery.data : undefined;
        const range = document ? normalizeSheetRange(document, binding.sheet, binding.range) : null;
        if (!range) return absent(documentQuery);
        const meta: DataMeta = { total: range.rows.length, truncated: false };
        return {
          data: { source: "rows", ...range, meta },
          isLoading: false,
          isUnbound: false,
          isRestricted: false,
          refetch,
          meta,
        };
      }

      case "app": {
        // A definition that never had the app filled in, or a canvas with no
        // dashboard behind it (a preview). Neither is an error.
        if (!binding.app_uid || !binding.endpoint_id || typeof dashboardId !== "number") {
          return unbound();
        }
        if (appCatalogQuery.isLoading) {
          return {
            data: emptyDataFor(source),
            isLoading: true,
            isUnbound: false,
            isRestricted: false,
            refetch,
          };
        }
        // A catalog that failed to load says nothing about whether this app is
        // installed, so it must not be read as "not installed" — that would
        // render every app widget on the dashboard as unconfigured and invite
        // someone to repoint bindings that were never wrong.
        if (appCatalogQuery.isError) {
          return {
            data: emptyDataFor(source),
            isLoading: false,
            isUnbound: false,
            isRestricted: false,
            refetch,
            errorCode: WidgetErrorCode.APP_UNAVAILABLE,
          };
        }
        // The catalog answered and the app is not in it: uninstalled, or
        // switched off. Said plainly rather than rendered as an access outcome
        // — the definition is the guild's and stays stored, and the tile
        // becomes the surface that asks for the app to be reconnected.
        const appInstalled = (appCatalogQuery.data?.items ?? []).some(
          (item) => item.app_uid === binding.app_uid
        );
        if (!appInstalled) {
          return {
            data: emptyDataFor(source),
            isLoading: false,
            isUnbound: false,
            isRestricted: false,
            refetch,
            errorCode: WidgetErrorCode.APP_NOT_INSTALLED,
          };
        }
        // Installed, but its pinned version stopped offering this source —
        // the catalog answered, so this is absence rather than a failure.
        if (!appBinding) return absent({ isLoading: false, isError: false });
        // An app that stopped answering does not blank a tile that already has
        // rows: React Query keeps the last good body for this key, and showing
        // it is more useful than showing nothing. The error tile is for when
        // there is genuinely nothing to draw.
        if (appQuery.isError && !appQuery.data) {
          return {
            data: emptyDataFor(source),
            isLoading: false,
            isUnbound: false,
            isRestricted: false,
            refetch,
            errorCode: WidgetErrorCode.APP_UNAVAILABLE,
          };
        }
        const rows = appQuery.data?.rows ?? [];
        const values = appQuery.data?.values ?? {};
        return {
          // Already read through the endpoint's declared returns on the way
          // here. Nothing on this side looks inside either half; the sandbox is
          // handed them as values.
          data: { source, rows, values, meta: { total: rows.length } },
          isLoading: appQuery.isLoading,
          isUnbound: false,
          isRestricted: false,
          refetch,
          meta: { total: rows.length },
        };
      }

      default:
        return unbound();
    }
  }, [
    source,
    initiativeId,
    binding.sql,
    binding.document_id,
    binding.range,
    binding.sheet,
    sqlQuery.data,
    sqlQuery.isLoading,
    sqlQuery.isError,
    documentQuery.data,
    documentQuery.isLoading,
    documentQuery.isError,
    scoped,
    dashboardId,
    binding.app_uid,
    binding.endpoint_id,
    appBinding,
    appCatalogQuery.data,
    appCatalogQuery.isLoading,
    appCatalogQuery.isError,
    appQuery.data,
    appQuery.isLoading,
    appQuery.isError,
    refetch,
    documentQuery,
  ]);
}
