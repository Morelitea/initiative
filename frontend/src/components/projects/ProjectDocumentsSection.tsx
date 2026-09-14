import { FilePlus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { CreateDocumentDialog } from "@/components/documents/CreateDocumentDialog";
import { RelationsSection } from "@/components/entities/RelationsSection";
import { Button } from "@/components/ui/button";

type ProjectDocumentsSectionProps = {
  projectId: number;
  projectName: string;
  initiativeId: number;
  canCreate: boolean;
  canAttach: boolean;
};

/**
 * What a project is connected to.
 *
 * This was a carousel of document cards with a documents-only picker, which
 * could attach one kind of thing out of the fourteen a link may name. It is the
 * generic relations surface now, and the shortcut that made a new document
 * already attached to the project is kept — creating the thing you are about to
 * attach is worth a button of its own, which searching for an existing one is
 * not.
 *
 * A project holding only documents looks the way it always did: a heading with
 * nothing under it is not drawn, so the other kinds of link appear only once
 * somebody makes one.
 */
export const ProjectDocumentsSection = ({
  projectId,
  projectName,
  initiativeId,
  canCreate,
  canAttach,
}: ProjectDocumentsSectionProps) => {
  const { t } = useTranslation("projects");
  const [createOpen, setCreateOpen] = useState(false);

  return (
    <>
      <RelationsSection
        entity={{ type: SearchEntityType.project, id: projectId }}
        initiativeId={initiativeId}
        anchorTool={{ tool: Tool.project, id: projectId }}
        canEdit={canAttach}
        collapseKey={`project:${projectId}:documentsCollapsed`}
        entityTitle={projectName}
        /* The shelf this section has always been. A project's attachments are
           browsed along rather than read down, and a carousel says "there is
           more this way" where a grid just runs out. */
        defaultLayout="carousel"
        headerActions={
          canCreate ? (
            <Button type="button" size="sm" onClick={() => setCreateOpen(true)}>
              <FilePlus className="h-4 w-4" />
              {t("documents.newDocument")}
            </Button>
          ) : null
        }
      />
      <CreateDocumentDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        initiativeId={initiativeId}
        projectId={projectId}
      />
    </>
  );
};
