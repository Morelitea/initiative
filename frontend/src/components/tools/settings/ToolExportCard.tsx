/**
 * The export card every tool's Advanced section carries.
 *
 * An export hands the whole thing over, so it is offered to whoever may also
 * delete it — the owner rung, which the server checks again — and it lives
 * here rather than in the tool's header. Everything it needs is derived from
 * the tool: the endpoint, the selector param and the formats. A tool whose
 * formats depend on the entity (a document's type) passes them as
 * `exportOptions` on its settings layout.
 */

import { useTranslation } from "react-i18next";

import { ExportButton } from "@/components/exports/ExportButton";
import { TOOL_EXPORT_FORMATS } from "@/components/exports/formats";
import { useToolSettings } from "@/components/tools/settings/ToolSettingsContext";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { exportFilenameStem } from "@/lib/exportDownload";
import {
  toolEnvelopeType,
  toolExportEndpoint,
  toolExportIdParam,
  toolKebabSingular,
} from "@/lib/tools";

export const ToolExportCard = () => {
  const { t } = useTranslation(["common", "exports"]);
  const { tool, entity, isOwner, exportOptions } = useToolSettings();

  const baseFormats = exportOptions?.formats ?? TOOL_EXPORT_FORMATS[tool] ?? [];
  if (!isOwner || baseFormats.length === 0) {
    return null;
  }

  const stem = exportFilenameStem(entity.name, toolKebabSingular(tool));
  // The importable envelope keeps the name the importer answers to.
  const formats = baseFormats.map((option) =>
    option.format === "json" && !option.filenameStem
      ? { ...option, filenameStem: `${stem}.${toolEnvelopeType(tool)}` }
      : option
  );

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{t("common:toolSettings.export.title")}</CardTitle>
        <CardDescription>{t("common:toolSettings.export.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <ExportButton
          endpoint={toolExportEndpoint(tool)}
          params={{ [toolExportIdParam(tool)]: entity.id }}
          formats={formats}
          filenameStem={stem}
          extraActions={exportOptions?.extraActions}
          // A single format is the button itself, so the button names the file
          // it downloads; with a menu, each entry does.
          label={
            formats.length === 1 && !exportOptions?.extraActions?.length
              ? t(`exports:${formats[0].labelKey}` as never)
              : t("common:toolSettings.export.button")
          }
          variant="default"
        />
      </CardContent>
    </Card>
  );
};
