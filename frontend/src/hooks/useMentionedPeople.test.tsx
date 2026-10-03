import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { buildUserSummary } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { MentionText } from "@/components/user/MentionText";
import { MentionedPeopleScope, ReportMentionedPeople } from "@/hooks/useMentionedPeople";

/** Answers every id it is asked about, named after the community asked, and
 *  keeps each request's ids. */
const answerEveryone = () => {
  const asked: { communityId: string; ids: string[] }[] = [];
  server.use(
    http.get("*/api/v1/c/:communityId/users/search", ({ params, request }) => {
      const ids = new URL(request.url).searchParams.getAll("user_id");
      asked.push({ communityId: String(params.communityId), ids });
      const items = ids.map((id) =>
        buildUserSummary({ id: Number(id), display_name: `Person ${id} of ${params.communityId}` })
      );
      return HttpResponse.json({ items, total: items.length, page: 1, page_size: 100 });
    })
  );
  return asked;
};

describe("everyone a page mentions", () => {
  it("names every one of them, however many one request can carry", async () => {
    const asked = answerEveryone();
    const text = Array.from({ length: 150 }, (_, index) => `@[](${index + 1})`).join(" ");

    renderWithProviders(
      <MentionedPeopleScope>
        <ReportMentionedPeople texts={[text]} />
        <MentionText text={text} disableLink />
      </MentionedPeopleScope>
    );

    expect(await screen.findByText("@Person 150 of 1")).toBeInTheDocument();
    expect(screen.getByText("@Person 1 of 1")).toBeInTheDocument();
    expect(asked.map(({ ids }) => ids.length)).toEqual([100, 50]);
  });

  it("reads each person in the community that mentioned them", async () => {
    // A list across communities: the same id is somebody else, or nobody,
    // in each one.
    const asked = answerEveryone();

    renderWithProviders(
      <MentionedPeopleScope>
        <ReportMentionedPeople communityId={1} texts={["@[](7)"]} />
        <ReportMentionedPeople communityId={2} texts={["@[](7)"]} />
        <MentionText text="@[](7)" communityId={1} disableLink /> /{" "}
        <MentionText text="@[](7)" communityId={2} disableLink />
      </MentionedPeopleScope>
    );

    expect(await screen.findByText("@Person 7 of 1")).toBeInTheDocument();
    expect(screen.getByText("@Person 7 of 2")).toBeInTheDocument();
    expect(asked.map(({ communityId }) => communityId).sort()).toEqual(["1", "2"]);
  });
});
