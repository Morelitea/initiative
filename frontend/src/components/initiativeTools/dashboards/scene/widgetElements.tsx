/**
 * The widget elements as components, for a widget template to place.
 *
 * Each checks the props the template gave it with the widget validator, the
 * same rules and limits a scene is held to, then draws them with the trusted
 * node component. A bound value is data the compiler never saw, so nothing
 * reaches the page unchecked. A failed check draws the error in place of that
 * one picture, not the whole widget.
 *
 * There are two sets: one draws each picture, the other draws the same numbers
 * as a table, for the tile's table view.
 */

import type { ComponentType } from "react";

import { WIDGET_ELEMENTS } from "@/lib/widgets/elements";
import { validateScene } from "@/lib/widgets/validateScene";

import { WidgetError } from "../WidgetError";
import { SceneRenderer } from "./SceneRenderer";
import { SceneTableView } from "./SceneTableView";

type ElementComponent = ComponentType<{ props: Record<string, unknown> }>;

const elementsFor = (view: "scene" | "table"): Record<string, ElementComponent> =>
  Object.fromEntries(
    Object.entries(WIDGET_ELEMENTS).map(([name, definition]) => {
      const Element: ElementComponent = ({ props }) => {
        // The kind last, so a prop cannot claim to be another picture.
        const checked = validateScene({ v: 1, scene: { ...props, kind: definition.kind } });
        if (!checked.ok) return <WidgetError code={checked.code} />;
        return view === "table" ? (
          <SceneTableView node={checked.spec.scene} />
        ) : (
          <SceneRenderer node={checked.spec.scene} />
        );
      };
      Element.displayName = `WidgetElement(${name})`;
      return [name, Element];
    })
  );

export const WIDGET_ELEMENT_COMPONENTS = {
  scene: elementsFor("scene"),
  table: elementsFor("table"),
} as const;
