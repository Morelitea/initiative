import { useSearch } from "@tanstack/react-router";
import { CircleCheck, CircleX, Clock, TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import { LogoIcon } from "@/components/LogoIcon";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * How a vendor flow ended, in the four ways it can.
 *
 * The same closed set every app returns, which is the point: an app knows a
 * connection handle and a guild id and has never been told what language the
 * member reads. It hands them back with one word, and the sentence is written
 * here — once, in every language this product speaks.
 *
 * They are told apart by whose move is next, because that is the only thing the
 * member needs from this page.
 */
const OUTCOMES = {
  connected: { icon: CircleCheck, tone: "text-emerald-600 dark:text-emerald-400" },
  refused: { icon: CircleX, tone: "text-destructive" },
  expired: { icon: Clock, tone: "text-muted-foreground" },
  not_recorded: { icon: TriangleAlert, tone: "text-amber-600 dark:text-amber-400" },
} as const;

type Outcome = keyof typeof OUTCOMES;

function isOutcome(value: unknown): value is Outcome {
  return typeof value === "string" && value in OUTCOMES;
}

/**
 * Where a member lands after an app's vendor flow.
 *
 * Deliberately terminal, and deliberately outside the authenticated tree. The
 * connect opens in its own tab, so this is the last thing in that tab and the
 * only useful action is closing it — the member's real session is still sitting
 * where they left it. Requiring a session to read one word back would mean a
 * login screen at the end of a flow that already succeeded.
 */
export function AppConnectedPage() {
  const { t } = useTranslation(["apps"]);
  const search = useSearch({ strict: false }) as { outcome?: string };

  // Anything else is a link that was edited or truncated. `expired` is the
  // right thing to say about it: start again from the app's settings, which is
  // the remedy for every unreadable ending.
  const outcome: Outcome = isOutcome(search.outcome) ? search.outcome : "expired";
  const { icon: Icon, tone } = OUTCOMES[outcome];

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="items-center text-center">
          <LogoIcon className="mb-2 h-8 w-8" />
          <Icon className={`h-8 w-8 ${tone}`} aria-hidden />
          <CardTitle>{t(`apps:connected.${outcome}.title`)}</CardTitle>
          <CardDescription>{t(`apps:connected.${outcome}.body`)}</CardDescription>
        </CardHeader>
        <CardContent className="text-center text-muted-foreground text-sm">
          {t("apps:connected.closeTab")}
        </CardContent>
      </Card>
    </div>
  );
}
