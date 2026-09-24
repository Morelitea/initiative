import { MessageSquare } from "lucide-react";
import { useTranslation } from "react-i18next";

import { MemberSelect } from "@/components/members/MemberSearchSelect";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { creditsImportsToOthers } from "@/lib/permissions";

/** One row of the plan's `people` list.
 *
 * Declared here rather than imported: a job's `plan` crosses the wire as a
 * free-form object (the shape depends on which importer produced it), so the
 * generated client has no type for what is inside it. */
export interface PlanPerson {
  handle: string;
  name?: string | null;
  comment_count: number;
  suggested_user_id?: number | null;
}

export interface ImportPeopleStepProps {
  /** Everyone the archive quotes, most-quoted first (the plan's order). */
  people: PlanPerson[];
  /** Source handle → the account chosen for it, or null for "leave it". */
  value: Record<string, number | null>;
  onChange: (next: Record<string, number | null>) => void;
}

/** Who each name in the archive is, here.
 *
 * An export names people by the handle they had where it came from, and only
 * a person can say whether that is the same person as somebody on this
 * server. Rows arrive pre-filled where the handle matched a member exactly;
 * everything else is blank, because a display name that merely looks similar
 * is how one person's words end up under another person's face.
 *
 * Leaving a row blank is a real answer, not an unfinished one: those comments
 * keep the name they arrived with and are credited to no account at all.
 *
 * Matching a name to another member is the community admin's (or the seat's)
 * to do; anybody else is offered themselves or nobody, the same rule the
 * server applies to the confirm. */
export function ImportPeopleStep({ people, value, onChange }: ImportPeopleStepProps) {
  const { t } = useTranslation("imports");
  const { user } = useAuth();
  const { activeGuild } = useGuilds();
  const anyMember = creditsImportsToOthers(activeGuild);

  return (
    <div className="space-y-4">
      <p className="text-muted-foreground text-xs">
        {anyMember ? t("wizard.people.note") : t("wizard.people.noteSelfOnly")}
      </p>
      <ul className="space-y-3">
        {people.map((person) => {
          const who = person.name?.trim() || person.handle;
          return (
            <li key={person.handle} className="space-y-1.5 rounded-lg border p-3">
              {/* Not a <label htmlFor>: the control below is a combobox, which
                  takes its accessible name from aria-label rather than from a
                  label pointing at it. */}
              <p className="font-medium text-sm">{who}</p>
              <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-muted-foreground text-xs">
                <span className="font-mono">{person.handle}</span>
                {person.comment_count > 0 && (
                  <span className="inline-flex items-center gap-1">
                    <MessageSquare className="h-3 w-3 shrink-0" />
                    {t("wizard.people.comments", { count: person.comment_count })}
                  </span>
                )}
              </p>
              {anyMember ? (
                <MemberSelect
                  scope={{ type: "guild" }}
                  value={value[person.handle] ?? null}
                  onChange={(id) => onChange({ ...value, [person.handle]: id })}
                  placeholder={t("wizard.people.unmapped")}
                  aria-label={t("wizard.people.pickerLabel", { name: who })}
                />
              ) : (
                <Select
                  value={user != null && value[person.handle] === user.id ? "me" : "nobody"}
                  onValueChange={(choice) =>
                    onChange({
                      ...value,
                      [person.handle]: choice === "me" && user != null ? user.id : null,
                    })
                  }
                >
                  <SelectTrigger aria-label={t("wizard.people.pickerLabel", { name: who })}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="nobody">{t("wizard.people.unmapped")}</SelectItem>
                    {user != null && <SelectItem value="me">{t("wizard.people.me")}</SelectItem>}
                  </SelectContent>
                </Select>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
