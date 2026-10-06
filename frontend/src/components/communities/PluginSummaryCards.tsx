import { useTranslation } from "react-i18next";

import type { CommunityPluginRead } from "@/api/generated/initiativeAPI.schemas";
import { useReadPluginSummary } from "@/api/generated/plugins/plugins";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityPlugins } from "@/hooks/useCommunityPlugins";
import { parseDateValue } from "@/lib/formatDate";
import { type LocalizedText, localized } from "@/lib/widgets/widgetMeta";

/** One declared return of a summary endpoint, as the pinned manifest says it. */
interface SummaryReturn {
  key: string;
  type: string;
  label?: LocalizedText;
  list?: boolean;
  of?: string;
}

/** The returns of the read an install names as its `community_summary`, or
 *  null when it names none. */
const summaryReturns = (plugin: CommunityPluginRead): SummaryReturn[] | null => {
  const definition = plugin.definition as {
    community_summary?: string;
    endpoints?: { id: string; returns?: SummaryReturn[] }[];
  };
  const id = definition.community_summary;
  if (!id) return null;
  const endpoint = definition.endpoints?.find((candidate) => candidate.id === id);
  return endpoint?.returns ?? null;
};

/** A figure as the viewer's language writes it, or null when there is none. */
const formatValue = (value: unknown, type: string, lang: string): string | null => {
  if (value == null) return null;
  if (type === "int" && typeof value === "number") {
    return new Intl.NumberFormat(lang).format(value);
  }
  if (type === "datetime") {
    const date = parseDateValue(String(value));
    return date ? new Intl.DateTimeFormat(lang, { dateStyle: "long" }).format(date) : null;
  }
  if (type === "bool") return null;
  return String(value);
};

const PluginSummaryCard = ({
  plugin,
  returns,
}: {
  plugin: CommunityPluginRead;
  returns: SummaryReturn[];
}) => {
  const { t, i18n } = useTranslation(["communities", "common"]);
  const lang = i18n.resolvedLanguage ?? i18n.language;
  const communityId = useActiveCommunityId();
  const { data, isError } = useReadPluginSummary(communityId, plugin.id);
  const values = (data?.values ?? {}) as Record<string, unknown>;

  // A return another one is counted against is drawn inside that measure.
  const ceilings = new Set(returns.flatMap((item) => (item.of ? [item.of] : [])));
  const figures = returns.filter((item) => !item.list && !ceilings.has(item.key));

  return (
    <Card>
      <CardHeader>
        <CardTitle>{plugin.name}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {isError ? (
          <p className="text-muted-foreground text-sm">{t("usagePanel.summaryUnavailable")}</p>
        ) : data ? (
          figures.map((item) => {
            const label = localized(item.label, lang) ?? item.key;
            const used = values[item.key];
            const ceiling = item.of ? values[item.of] : null;
            const shown = formatValue(used, item.type, lang);
            if (shown == null) return null;
            const max =
              typeof ceiling === "number" && ceiling > 0 && typeof used === "number"
                ? ceiling
                : null;
            return (
              <div key={item.key} className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="font-medium">{label}</span>
                  <span className="text-muted-foreground">
                    {max == null
                      ? shown
                      : t("usagePanel.usedOfMax", {
                          used: shown,
                          max: formatValue(max, "int", lang),
                        })}
                  </span>
                </div>
                {max != null && (
                  <Progress value={Math.min(100, Math.round(((used as number) / max) * 100))} />
                )}
              </div>
            );
          })
        ) : null}
      </CardContent>
    </Card>
  );
};

/** Where the community stands with each installed plug-in that says.
 *
 * On the Usage tab, below the community's own figures. A plug-in whose manifest
 * names a `community_summary` gets a card titled with its install's name, and
 * every figure on it is labelled by the plug-in's own declaration — so nothing
 * here knows what any plug-in measures. One read per card, on the settings
 * rung; a plug-in that does not answer says so on its own card. */
export const PluginSummaryCards = () => {
  const { data } = useCommunityPlugins();
  const summarised = (data?.items ?? []).flatMap((plugin) => {
    const returns = plugin.enabled ? summaryReturns(plugin) : null;
    return returns?.length ? [{ plugin, returns }] : [];
  });

  return (
    <>
      {summarised.map(({ plugin, returns }) => (
        <PluginSummaryCard key={plugin.id} plugin={plugin} returns={returns} />
      ))}
    </>
  );
};
