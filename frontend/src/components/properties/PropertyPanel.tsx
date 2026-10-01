import type { PropertySummary, PropertyTarget } from "@/api/generated/initiativeAPI.schemas";

import { AddPropertyButton } from "./AddPropertyButton";
import { PropertyList, type PropertyListProps } from "./PropertyList";
import { usePendingProperties } from "./usePendingProperties";

const NONE: PropertySummary[] = [];

export interface PropertyPanelProps {
  target: PropertyTarget;
  entityId: number;
  /** The row's properties as the server last sent them. */
  saved: PropertySummary[] | undefined;
  /** The initiative whose definitions may be added. */
  initiativeId: number;
  canOpen?: PropertyListProps["canOpen"];
  disabled?: boolean;
}

/**
 * The properties on one tool or sub-tool, and the button that adds another.
 * Every value is saved as it changes, so it needs no Save of its own.
 *
 * Keyed by the row: a host that stays on screen while it moves to another row
 * (a wiki page's drawer, a document opened from a document) gets a fresh list,
 * so one row's drafts and additions never reach the next.
 */
export const PropertyPanel = (props: PropertyPanelProps) => (
  <RowProperties key={`${props.target}:${props.entityId}`} {...props} />
);

const RowProperties = ({
  target,
  entityId,
  saved,
  initiativeId,
  canOpen,
  disabled = false,
}: PropertyPanelProps) => {
  const attached = usePendingProperties(saved ?? NONE);

  return (
    <div className="space-y-3">
      <PropertyList
        target={target}
        entityId={entityId}
        properties={attached.properties}
        unsaved={attached.unsavedIds}
        disabled={disabled}
        initiativeId={initiativeId}
        canOpen={canOpen}
      />
      <AddPropertyButton
        initiativeId={initiativeId}
        currentPropertyIds={attached.propertyIds}
        onAdd={attached.add}
        disabled={disabled}
      />
    </div>
  );
};
