import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SerializedEditorState } from "lexical";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { Editor } from "@/components/ui/editor/editor";

const paragraph = (text: string) => ({
  type: "paragraph",
  version: 1,
  direction: null,
  format: "",
  indent: 0,
  textFormat: 0,
  textStyle: "",
  children: [{ type: "text", version: 1, detail: 0, format: 0, mode: "normal", style: "", text }],
});

const embed = (entityId: number, text: string, collapsed = false) => ({
  type: "reference-embed",
  version: 1,
  entityType: "file",
  entityId,
  text,
  collapsed,
});

const page = (...children: object[]) => ({
  root: { type: "root", version: 1, direction: null, format: "", indent: 0, children },
});

// Two pages embedding each other: 1 embeds 2, and 2 embeds 1 back.
const OUTER = page(paragraph("The outer page."), embed(2, "Inner"));
const INNER = page(paragraph("Here be dragons."), embed(1, "Outer"));

const BODIES: Record<string, { title: string; body: object }> = {
  "file:1": { title: "Outer", body: OUTER },
  "file:2": { title: "Inner", body: INNER },
};

const serveBodies = () =>
  server.use(
    communityHttp.get("/smart-chips/embeds", ({ request }) => {
      const refs = new URL(request.url).searchParams.getAll("ref");
      return HttpResponse.json({
        items: refs.map((ref) => ({
          ref,
          entity_type: "file",
          title: BODIES[ref].title,
          description: null,
          body: BODIES[ref].body,
        })),
      });
    })
  );

describe("an embedded page", () => {
  it("folds to its name, and saves that with the page", async () => {
    serveBodies();
    const saved: SerializedEditorState[] = [];
    const folded = page(paragraph("The outer page."), embed(2, "Inner", true));

    renderPage(() => (
      <Editor
        editorSerializedState={folded as unknown as SerializedEditorState}
        onSerializedChange={(state) => saved.push(state)}
      />
    ));

    const expand = await screen.findByRole("button", { name: "Expand" }, { timeout: 4000 });
    expect(screen.queryByText("Here be dragons.")).not.toBeInTheDocument();

    await userEvent.click(expand);
    expect(await screen.findByText("Here be dragons.", {}, { timeout: 4000 })).toBeInTheDocument();
    await waitFor(() => {
      const last = saved.at(-1)?.root.children[1] as { collapsed?: boolean } | undefined;
      expect(last?.collapsed).toBe(false);
    });
  });

  it("shows what the page says, and stops one level down", async () => {
    serveBodies();

    renderPage(() => (
      <Editor
        editorSerializedState={OUTER as unknown as SerializedEditorState}
        readOnly
        showToolbar={false}
      />
    ));

    expect(await screen.findByText("Here be dragons.", {}, { timeout: 4000 })).toBeInTheDocument();
    // The inner page's embed of the outer one is a name, not the outer page again.
    await waitFor(() => expect(screen.getByRole("button", { name: "Outer" })).toBeInTheDocument());
    expect(screen.getAllByText("The outer page.")).toHaveLength(1);
  });
});
