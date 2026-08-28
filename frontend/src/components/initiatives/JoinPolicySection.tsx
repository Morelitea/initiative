/**
 * How guild members may enter this initiative.
 *
 * The policy governs only how a membership row comes to exist — never what a
 * member may then see, which stays with initiative membership and per-resource
 * sharing. Phase 1 offers the two ends: closed, or open to any guild member.
 * The middle option (`request`) arrives with the request flow, and is listed
 * here only when the initiative is already set to it, so a save from this
 * screen can never silently downgrade it.
 */

import { useTranslation } from "react-i18next";

import { InitiativeJoinPolicy } from "@/api/generated/initiativeAPI.schemas";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";

/** The policies a manager may choose from here. */
const SELECTABLE_POLICIES: readonly InitiativeJoinPolicy[] = [
  InitiativeJoinPolicy.private,
  InitiativeJoinPolicy.open,
];

const POLICY_LABEL_KEY: Record<InitiativeJoinPolicy, string> = {
  [InitiativeJoinPolicy.private]: "settings.joinPolicy.privateLabel",
  [InitiativeJoinPolicy.request]: "settings.joinPolicy.requestLabel",
  [InitiativeJoinPolicy.open]: "settings.joinPolicy.openLabel",
};

const POLICY_HELP_KEY: Record<InitiativeJoinPolicy, string> = {
  [InitiativeJoinPolicy.private]: "settings.joinPolicy.privateHelp",
  [InitiativeJoinPolicy.request]: "settings.joinPolicy.requestHelp",
  [InitiativeJoinPolicy.open]: "settings.joinPolicy.openHelp",
};

export interface JoinPolicySectionProps {
  value: InitiativeJoinPolicy;
  onChange: (value: InitiativeJoinPolicy) => void;
  canManage: boolean;
  isSaving: boolean;
  /** "card" (settings, the default) or "plain" for embedding in a form. */
  layout?: "card" | "plain";
  /** Keeps radio ids unique when more than one instance is mounted. */
  idPrefix?: string;
}

export const JoinPolicySection = ({
  value,
  onChange,
  canManage,
  isSaving,
  layout = "card",
  idPrefix,
}: JoinPolicySectionProps) => {
  const { t } = useTranslation("initiatives");
  const disabled = !canManage || isSaving;
  const radioId = (policy: InitiativeJoinPolicy) =>
    `${idPrefix ? `${idPrefix}-` : ""}join-policy-${policy}`;

  const policies: readonly InitiativeJoinPolicy[] = SELECTABLE_POLICIES.some(
    (policy) => policy === value
  )
    ? SELECTABLE_POLICIES
    : [...SELECTABLE_POLICIES, value];

  const radios = (
    <RadioGroup
      value={value}
      onValueChange={(next) => onChange(next as InitiativeJoinPolicy)}
      disabled={disabled}
      className="gap-3"
      aria-label={t("settings.joinPolicy.title")}
    >
      {policies.map((policy) => (
        <div key={policy} className="flex items-start gap-3 rounded-md border px-3 py-3">
          <RadioGroupItem id={radioId(policy)} value={policy} className="mt-1" />
          <div className="min-w-0 space-y-0.5">
            <Label htmlFor={radioId(policy)} className="font-medium">
              {t(POLICY_LABEL_KEY[policy] as never)}
            </Label>
            <p className="text-muted-foreground text-xs">{t(POLICY_HELP_KEY[policy] as never)}</p>
          </div>
        </div>
      ))}
    </RadioGroup>
  );

  if (layout === "plain") {
    return radios;
  }

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>{t("settings.joinPolicy.title")}</CardTitle>
        <CardDescription>{t("settings.joinPolicy.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {radios}
        {canManage ? null : (
          <p className="mt-3 text-muted-foreground text-sm">{t("settings.editPermissionNote")}</p>
        )}
      </CardContent>
    </Card>
  );
};
