/**
 * The start flow: what somebody came for, then what that answer needs.
 *
 * Four paths — an invite, joining a listed community, a space of one's own,
 * a community for a group — and only the ones this deployment can honour are
 * offered. Signed out, the flow ends by making the account, which carries the
 * community with it. Signed in with no community, it is the same questions
 * without the account, and ends by making the community.
 *
 * Every question has an answer already filled in, so Continue always works;
 * only what an account cannot be made without (an address, a handle, a way to
 * sign in) has to be typed.
 */

import { Link, useNavigate } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useBootstrapStatusApiV1AuthBootstrapGet } from "@/api/generated/auth/auth";
import {
  createGuildInviteApiV1CommunitiesGuildIdInvitesPost,
  getInviteStatusApiV1CommunitiesInviteCodeGet,
} from "@/api/generated/communities/communities";
import type { GuildInviteStatus, GuildRead } from "@/api/generated/initiativeAPI.schemas";
import { BirthdateField } from "@/components/auth/BirthdateField";
import { CaptchaWidget } from "@/components/auth/CaptchaWidget";
import { EmailOtpCard } from "@/components/auth/EmailOtpCard";
import { LegalNotice } from "@/components/auth/LegalNotice";
import { SignInFrame } from "@/components/auth/SignInFrame";
import { useAgeConfirmation } from "@/components/auth/useAgeConfirmation";
import { RecoveryCodesPanel } from "@/components/settings/RecoveryCodesPanel";
import { UsernameField } from "@/components/UsernameField";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { Textarea } from "@/components/ui/textarea";
import { WizardFrame } from "@/components/ui/wizard-dialog";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useBillingCatalog } from "@/hooks/useBillingCatalog";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import { useLandOnStarter, useOpenDirectory, useSeedStarter } from "@/hooks/useFinishPendingStart";
import { useGuilds } from "@/hooks/useGuilds";
import { useServer } from "@/hooks/useServer";
import { useWizard } from "@/hooks/useWizard";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { GUILD_CATEGORIES, guildCategoryLabel } from "@/lib/guildCategories";
import {
  browserOffersPasskeys,
  describePasskeyPromptError,
  signUpWithPasskey,
} from "@/lib/passkeys";
import { PASSWORD_MIN_LENGTH, validatePasswordLocal } from "@/lib/passwordPolicy";
import {
  clearStart,
  findStartedCommunity,
  freshAnswers,
  newCommunity,
  readStartDraft,
  type StartAnswers,
  type StartPath,
  savePendingStart,
  saveStartDraft,
} from "@/lib/startFlow";
import { TIMEZONE_OPTIONS } from "@/lib/timezones";
import { slugifyUsername } from "@/lib/usernames";
import { cn } from "@/lib/utils";

type Step =
  | "choose"
  | "invite"
  | "interest"
  | "you"
  | "personal"
  | "shared"
  | "plan"
  | "account"
  | "codes"
  | "finishing"
  | "people"
  | "checkEmail"
  | "underAge";

const PATH_ORDER: StartPath[] = ["invite", "join", "personal", "shared"];

/** The last part of a pasted invite link, or the code as typed. */
const inviteCodeFrom = (text: string): string =>
  text.trim().split(/[?#]/)[0].split("/").filter(Boolean).pop() ?? "";

export interface StartFlowProps {
  /** Signed in already: the flow makes a community rather than an account. */
  signedIn?: boolean;
  /** From the URL: go straight to the invited path. */
  inviteCode?: string;
  /** Signed in: true while a community is being made and set up, so the
   *  layout keeps the flow on screen once the account has one. */
  onBusy?: (busy: boolean) => void;
  /** Under the steps, inside the card. */
  footer?: ReactNode;
}

/** Waits for what decides which paths are offered, then starts the steps. */
export const StartFlow = (props: StartFlowProps) => {
  const { signedIn = false } = props;
  const { isLoading, communityDirectoryEnabled } = useAppConfig();
  const { canCreateGuilds } = useGuilds();
  const bootstrap = useBootstrapStatusApiV1AuthBootstrapGet({
    query: { enabled: !signedIn, retry: false },
  });

  if (isLoading || (!signedIn && bootstrap.isPending)) {
    return (
      <SignInFrame>
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </SignInFrame>
    );
  }

  // Signing up without an invite needs public registration (which the server
  // reports closed when communities cannot be made either). Signed in, making
  // a community needs that account to be allowed to.
  const registrationOpen = signedIn || bootstrap.data?.public_registration_enabled !== false;
  const paths = PATH_ORDER.filter((path) => {
    if (path === "invite") return true;
    if (!registrationOpen) return false;
    if (path === "join") return communityDirectoryEnabled;
    return !signedIn || canCreateGuilds;
  });
  return <StartSteps {...props} signedIn={signedIn} paths={paths} />;
};

const StartSteps = ({
  signedIn,
  inviteCode: urlCode,
  onBusy,
  footer,
  paths,
}: StartFlowProps & { signedIn: boolean; paths: StartPath[] }) => {
  const { t } = useTranslation(["auth", "common", "settings", "guilds"]);
  const { t: tCategory } = useTranslation(["guilds", "common"]);
  const navigate = useNavigate();
  const { user, register, login, applyPasskeySignIn } = useAuth();
  const { guilds, loading: guildsLoading, createGuild } = useGuilds();
  const {
    captcha,
    passwordLoginEnabled,
    passkeyLoginEnabled,
    emailOtpLoginEnabled,
    communityAgeGateEnabled,
  } = useAppConfig();
  const { isNativePlatform, getServerOrigin } = useServer();
  const { billing, openPortal, reserveTab } = useBillingPortal();
  // A plan is picked in both; only the web goes on to the portal. The native
  // app's pick travels with the new community, and the owner is emailed.
  const plansShown = Boolean(billing);
  const portalOpens = !isNativePlatform;
  const catalog = useBillingCatalog(plansShown ? billing?.url : null);
  const seed = useSeedStarter();
  const landOn = useLandOnStarter();
  const openDirectory = useOpenDirectory();

  const [answers, setAnswers] = useState<StartAnswers>(() => {
    const draft = readStartDraft();
    if (urlCode)
      return { ...(draft ?? freshAnswers("invite")), path: "invite", inviteCode: urlCode };
    if (draft && paths.includes(draft.path)) return draft;
    return freshAnswers(paths.includes("personal") ? "personal" : paths[0]);
  });
  // A reload or a trip to a password manager loses nothing.
  useEffect(() => saveStartDraft(answers), [answers]);
  const update = (patch: Partial<StartAnswers>) => setAnswers((prev) => ({ ...prev, ...patch }));

  // Held in memory only: the server keeps whether it was answered, never the date.
  const age = useAgeConfirmation(() => commit("finishing"));
  const ageAnswered = Boolean(user?.age_confirmed_at || user?.age_below_minimum_at);
  const asksAge = communityAgeGateEnabled && !(signedIn && ageAnswered);
  // Joining a listed community needs the answer; anywhere else it can wait.
  const ageRequired = asksAge && answers.path === "join";

  // Every name has an answer before anybody types one.
  const firstName = (signedIn ? (user?.full_name ?? "") : answers.fullName).trim().split(/\s+/)[0];
  const withDefaults = (a: StartAnswers): StartAnswers => {
    if (a.path !== "personal" && a.path !== "shared") return a;
    const group = a.path;
    return {
      ...a,
      communityName:
        a.communityName.trim() ||
        (firstName
          ? t(`start.${group}.nameDefault`, { name: firstName })
          : t(`start.${group}.nameFallback`)),
      initiativeName: a.initiativeName.trim() || t(`start.${group}.initiativeDefault`),
      listName: a.listName.trim() || (group === "personal" ? t("start.personal.listDefault") : ""),
    };
  };

  const tiers = (catalog.data?.tiers ?? []).filter(
    (tier) => tier.kind === "free_hosted" || tier.kind === "paid"
  );
  const entryTier = tiers.find((tier) => tier.kind === "free_hosted") ?? tiers[0];
  const chosenTier = tiers.find((tier) => tier.id === answers.planId) ?? entryTier;
  const wantsPlan =
    plansShown && answers.path === "shared" && Boolean(chosenTier) && chosenTier !== entryTier;
  // Opened inside the click that makes the account or community, so the
  // browser lets it through; pointed at the portal once there is a session.
  const pickedPlan = wantsPlan ? chosenTier?.id : undefined;
  const planTab = useRef<Window | null>(null);
  const reservePlanTab = () => {
    planTab.current?.close();
    planTab.current = wantsPlan && portalOpens ? reserveTab() : null;
  };
  const dropPlanTab = () => {
    planTab.current?.close();
    planTab.current = null;
  };

  const sequence = (path: StartPath): Step[] => {
    const you: Step[] = signedIn ? [] : ["you"];
    const account: Step[] = signedIn ? [] : ["account"];
    switch (path) {
      case "invite":
        return ["invite", ...you, ...account];
      case "join":
        return ["interest", ...(asksAge || !signedIn ? (["you"] as Step[]) : []), ...account];
      case "personal":
        return [...you, "personal", ...account];
      case "shared":
        return [...you, "shared", ...(plansShown ? (["plan"] as Step[]) : []), ...account];
    }
  };
  const flow: Step[] = [
    ...(paths.length > 1 && !urlCode ? (["choose"] as Step[]) : []),
    ...sequence(answers.path),
  ];
  const { step, go, back, commit, canGoBack, reset } = useWizard<Step>(flow[0]);
  const position = flow.indexOf(step);
  // An under-age answer is recorded and refused; the refreshed account says so.
  useEffect(() => {
    if (signedIn && step === "you" && user?.age_below_minimum_at) commit("underAge");
  }, [signedIn, step, user?.age_below_minimum_at, commit]);

  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // -- invite --------------------------------------------------------------
  const [invite, setInvite] = useState<{
    code: string;
    status: GuildInviteStatus | null;
    error: string | null;
    checking: boolean;
  }>({ code: "", status: null, error: null, checking: false });
  const checkInvite = async (code: string): Promise<boolean> => {
    setInvite({ code, status: null, error: null, checking: true });
    try {
      const status = await getInviteStatusApiV1CommunitiesInviteCodeGet(encodeURIComponent(code));
      setInvite({
        code,
        status,
        error: status.is_valid ? null : (status.reason ?? t("register.inviteNoLongerValid")),
        checking: false,
      });
      return status.is_valid;
    } catch {
      setInvite({ code, status: null, error: t("register.unableToLoadInvite"), checking: false });
      return false;
    }
  };
  // A code from the URL is checked as soon as the step shows it.
  const checkedUrlCode = useRef(false);
  useEffect(() => {
    if (checkedUrlCode.current || !urlCode || signedIn) return;
    checkedUrlCode.current = true;
    void checkInvite(inviteCodeFrom(urlCode));
  });

  // -- moving on -----------------------------------------------------------
  const next = () => {
    setError(null);
    const to = flow[position + 1];
    if (!to) {
      void finishSignedIn();
      return;
    }
    if (to === "personal" || to === "shared") setAnswers(withDefaults);
    go(to);
  };

  const choosePath = (path: StartPath) =>
    setAnswers((prev) =>
      prev.path === path
        ? prev
        : {
            ...freshAnswers(path, prev.inviteCode),
            fullName: prev.fullName,
            timezone: prev.timezone,
          }
    );

  const continueInvite = async () => {
    const code = inviteCodeFrom(answers.inviteCode);
    if (!code) return;
    if (signedIn) {
      await navigate({ to: "/invite/$code", params: { code } });
      return;
    }
    if ((invite.code === code && invite.status?.is_valid) || (await checkInvite(code))) next();
  };

  /** Signed in: the last question answered, so make what it asked for. */
  const madeGuild = useRef<GuildRead | null>(null);
  const finishSignedIn = async () => {
    if (answers.path === "join") {
      if (asksAge) await age.confirm();
      else commit("finishing");
      return;
    }
    const final = withDefaults(answers);
    setBusy(true);
    reservePlanTab();
    onBusy?.(true);
    try {
      madeGuild.current = await createGuild({
        name: final.communityName.trim(),
        description: final.description.trim() || undefined,
        plan: pickedPlan,
      });
      commit("finishing");
    } catch (err) {
      dropPlanTab();
      onBusy?.(false);
      setError(getErrorMessage(err, "guilds:unableToCreateGuild"));
    } finally {
      setBusy(false);
    }
  };

  // -- once signed in ------------------------------------------------------
  const [made, setMade] = useState<{ id: number; name: string } | null>(null);
  // A plan was picked but no tab could be held open for it: offered as a
  // button instead, which is a click of its own.
  const [planByButton, setPlanByButton] = useState(false);
  const finishing = useRef(false);
  const leave = async (to: () => Promise<unknown>) => {
    await to();
    onBusy?.(false);
  };
  useEffect(() => {
    if (step !== "finishing" || finishing.current || !user || guildsLoading) return;
    finishing.current = true;
    const final = withDefaults(answers);
    void (async () => {
      await clearStart();
      if (final.path === "join") {
        if (user.age_below_minimum_at) commit("underAge");
        else await leave(() => openDirectory(final.category));
        return;
      }
      if (final.path === "invite") {
        const guildId = invite.status?.guild_id;
        await leave(() =>
          guildId
            ? navigate({ to: "/c/$guildId", params: { guildId: String(guildId) } })
            : navigate({ to: "/" })
        );
        return;
      }
      const guild = madeGuild.current ?? findStartedCommunity(guilds, final);
      if (!guild) {
        dropPlanTab();
        await leave(() => navigate({ to: "/" }));
        return;
      }
      const starter = await seed(guild.id, final);
      if (final.path === "personal") {
        await leave(() => landOn(guild.id, starter));
        return;
      }
      if (planTab.current) {
        toast.info(t("guilds:billingSetup.opening", { guild: guild.name }));
        void openPortal(guild.id, "upgrade", planTab.current);
        planTab.current = null;
      } else if (wantsPlan && portalOpens) {
        setPlanByButton(true);
      }
      setMade({ id: guild.id, name: guild.name });
      commit("people");
    })();
  });

  // -- account -------------------------------------------------------------
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [captchaToken, setCaptchaToken] = useState("");
  // A captcha token is spent by being checked, so every attempt gets a fresh
  // widget: bumping this remounts it.
  const [captchaKey, setCaptchaKey] = useState(0);
  const [emailDoor, setEmailDoor] = useState(false);
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [held, setHeld] = useState<{ approval: boolean; underAge: boolean } | null>(null);
  const keysOffered = passkeyLoginEnabled && browserOffersPasskeys();
  const inviteParam = answers.path === "invite" ? inviteCodeFrom(answers.inviteCode) : undefined;
  const inviteBlocked = answers.path === "invite" && !invite.status?.is_valid;
  const accountIncomplete =
    !email.trim() || !username.trim() || (captcha !== null && !captchaToken) || inviteBlocked;

  const signUpDetails = () => {
    const final = withDefaults(answers);
    return {
      email: email.toLowerCase().trim(),
      username: username.trim().toLowerCase(),
      full_name: final.fullName.trim() || undefined,
      timezone: final.timezone,
      captcha_token: captcha ? captchaToken : undefined,
      community: newCommunity(final, pickedPlan),
      birthdate: age.birthdate || undefined,
    };
  };

  const afterAttempt = () => {
    setBusy(false);
    if (captcha) {
      setCaptchaToken("");
      setCaptchaKey((key) => key + 1);
    }
  };

  const submitPassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (password !== confirmPassword) {
      setError(t("register.passwordMismatch"));
      return;
    }
    const policyError = validatePasswordLocal(password);
    if (policyError) {
      setError(policyError);
      return;
    }
    reservePlanTab();
    setBusy(true);
    setError(null);
    const details = signUpDetails();
    try {
      const created = await register({ ...details, password, inviteCode: inviteParam });
      if (created.status === "active" && created.email_verified) {
        await login({ email: details.email, password });
        commit("finishing");
        return;
      }
      // Made, but it cannot sign in yet: the rest waits for its first sign-in
      // on this browser.
      dropPlanTab();
      const underAge = Boolean(created.age_below_minimum_at);
      await clearStart();
      if (answers.path !== "invite" && !(answers.path === "join" && underAge)) {
        await savePendingStart(details.email, withDefaults(answers));
      }
      setHeld({ approval: created.status !== "active", underAge });
      commit("checkEmail");
    } catch (err) {
      dropPlanTab();
      setError(getErrorMessage(err, "auth:register.defaultError"));
    } finally {
      afterAttempt();
    }
  };

  const submitPasskey = async () => {
    reservePlanTab();
    setBusy(true);
    setError(null);
    try {
      const madeAccount = await signUpWithPasskey(signUpDetails(), inviteParam);
      // Shown once, before anything else is awaited: an account with no
      // password gets back in with these.
      setRecoveryCodes(madeAccount.codes ?? []);
      commit("codes");
      await applyPasskeySignIn({ access_token: madeAccount.access_token });
    } catch (err) {
      dropPlanTab();
      const prompt = describePasskeyPromptError(err);
      setError(prompt ? t(prompt) : getErrorMessage(err, "auth:register.defaultError"));
    } finally {
      afterAttempt();
    }
  };

  // The emailed-code card takes the whole frame while it is open, as it does
  // on the sign-in page.
  if (emailDoor) {
    const details = signUpDetails();
    return (
      <SignInFrame fillPhone>
        <EmailOtpCard
          inviteCode={inviteParam}
          registration={{
            username: details.username,
            full_name: details.full_name,
            timezone: details.timezone,
            community: details.community,
            birthdate: details.birthdate,
          }}
          onCancel={() => setEmailDoor(false)}
          onSignedIn={(registered) => {
            setEmailDoor(false);
            if (registered) {
              commit("finishing");
              return;
            }
            // The address already had an account, so nothing was made: on to
            // the invite, or home.
            void clearStart();
            void (inviteParam
              ? navigate({ to: "/invite/$code", params: { code: inviteParam } })
              : navigate({ to: "/" }));
          }}
        />
      </SignInFrame>
    );
  }

  // -- the steps -----------------------------------------------------------
  const continueButton = (onClick: () => void, disabled = false) => (
    <Button type="button" className="w-full" onClick={onClick} disabled={busy || disabled}>
      {t("start.continue")}
    </Button>
  );
  const skipButton = (onSkip: () => void) => (
    <Button type="button" variant="ghost" className="w-full" onClick={onSkip} disabled={busy}>
      {t("start.skip")}
    </Button>
  );
  const field = (id: string, label: string, control: ReactNode, hint?: string) => (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      {control}
      {hint ? <p className="text-muted-foreground text-xs">{hint}</p> : null}
    </div>
  );
  const finalName = withDefaults(answers).communityName;
  const inviteLine = invite.checking
    ? t("register.checkingInvite")
    : invite.status?.is_valid
      ? invite.status.guild_name
        ? t("register.joiningGuild", { guildName: invite.status.guild_name })
        : t("register.joiningGuildDefault")
      : null;

  let title: string;
  let description: string | null = null;
  let body: ReactNode;
  switch (step) {
    case "choose":
      title = t("start.choose.title");
      description = t("start.choose.description");
      body = (
        <>
          <RadioGroup
            value={answers.path}
            onValueChange={(value) => choosePath(value as StartPath)}
            className="gap-2"
          >
            {paths.map((path) => (
              <Label
                key={path}
                htmlFor={`start-path-${path}`}
                className="flex cursor-pointer items-start gap-3 rounded-md border p-3 font-normal has-[[data-state=checked]]:border-primary"
              >
                <RadioGroupItem id={`start-path-${path}`} value={path} className="mt-0.5" />
                <span className="space-y-1">
                  <span className="block font-medium">{t(`start.choose.${path}`)}</span>
                  <span className="block text-muted-foreground text-sm">
                    {t(`start.choose.${path}Hint`)}
                  </span>
                </span>
              </Label>
            ))}
          </RadioGroup>
          {continueButton(next)}
        </>
      );
      break;

    case "invite":
      // Signing up by invite only: say so, in the words the closed sign-up
      // page always used.
      if (!signedIn && paths.length === 1) {
        title = t("inviteRequired.title");
        description = t("inviteRequired.subtitle");
      } else {
        title = t("start.invite.title");
        description = t("start.invite.description");
      }
      body = (
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void continueInvite();
          }}
        >
          {field(
            "start-invite-code",
            t("start.invite.codeLabel"),
            <Input
              id="start-invite-code"
              value={answers.inviteCode}
              onChange={(event) => update({ inviteCode: event.target.value })}
              autoCapitalize="none"
              autoComplete="off"
            />
          )}
          {inviteLine ? <p className="text-muted-foreground text-sm">{inviteLine}</p> : null}
          {invite.error ? <p className="text-destructive text-sm">{invite.error}</p> : null}
          <Button
            type="submit"
            className="w-full"
            disabled={invite.checking || !inviteCodeFrom(answers.inviteCode)}
          >
            {t("start.continue")}
          </Button>
        </form>
      );
      break;

    case "interest":
      title = t("start.interest.title");
      description = t("start.interest.description");
      body = (
        <>
          <div className="flex flex-wrap gap-2">
            {GUILD_CATEGORIES.map((category) => (
              <Button
                key={category}
                type="button"
                size="sm"
                variant={answers.category === category ? "default" : "outline"}
                aria-pressed={answers.category === category}
                onClick={() =>
                  update({ category: answers.category === category ? null : category })
                }
              >
                {guildCategoryLabel(category, tCategory)}
              </Button>
            ))}
          </div>
          {continueButton(next)}
          {skipButton(() => {
            update({ category: null });
            next();
          })}
        </>
      );
      break;

    case "you":
      if (signedIn) {
        // Signed in, this step is only ever the age question for joining.
        title = t("confirmAge.title");
        description = t("guilds:community.ageGateBody");
      } else {
        title = t("start.you.title");
        description = inviteLine ?? t("start.you.description");
      }
      body = (
        <>
          {signedIn
            ? null
            : field(
                "start-full-name",
                t("emailOtp.fullNameLabel"),
                <Input
                  id="start-full-name"
                  value={answers.fullName}
                  onChange={(event) => update({ fullName: event.target.value })}
                  autoComplete="name"
                  maxLength={255}
                />
              )}
          {signedIn
            ? null
            : field(
                "start-timezone",
                t("settings:profile.timezoneLabel"),
                <SearchableCombobox
                  items={TIMEZONE_OPTIONS.map((tz) => ({ value: tz, label: tz }))}
                  value={answers.timezone}
                  onValueChange={(timezone) => update({ timezone })}
                  placeholder={t("settings:profile.timezonePlaceholder")}
                  emptyMessage={t("settings:profile.timezoneEmpty")}
                />
              )}
          {asksAge ? (
            <BirthdateField
              id="start-birthdate"
              value={age.birthdate}
              onChange={age.setBirthdate}
              disabled={busy || age.submitting}
            />
          ) : null}
          {age.error ? <p className="text-destructive text-sm">{age.error}</p> : null}
          {continueButton(next, age.submitting || (ageRequired && !age.birthdate))}
          {ageRequired
            ? null
            : skipButton(() => {
                age.reset();
                next();
              })}
        </>
      );
      break;

    case "personal":
      title = t("start.personal.title");
      description = t("start.personal.description");
      body = (
        <>
          {field(
            "start-community-name",
            t("start.personal.nameLabel"),
            <Input
              id="start-community-name"
              value={answers.communityName}
              onChange={(event) => update({ communityName: event.target.value })}
              maxLength={255}
            />
          )}
          {field(
            "start-list-name",
            t("start.personal.listLabel"),
            <Input
              id="start-list-name"
              value={answers.listName}
              onChange={(event) => update({ listName: event.target.value })}
              maxLength={255}
            />
          )}
          {continueButton(next)}
        </>
      );
      break;

    case "shared":
      title = t("start.shared.title");
      description = t("start.shared.description");
      body = (
        <>
          {field(
            "start-community-name",
            t("start.shared.nameLabel"),
            <Input
              id="start-community-name"
              value={answers.communityName}
              onChange={(event) => update({ communityName: event.target.value })}
              maxLength={255}
            />
          )}
          {field(
            "start-description",
            t("start.shared.descriptionLabel"),
            <Textarea
              id="start-description"
              value={answers.description}
              onChange={(event) => update({ description: event.target.value })}
              rows={3}
            />
          )}
          {field(
            "start-initiative-name",
            t("start.shared.initiativeLabel"),
            <Input
              id="start-initiative-name"
              value={answers.initiativeName}
              onChange={(event) => update({ initiativeName: event.target.value })}
              maxLength={255}
            />,
            t("start.shared.initiativeHint")
          )}
          {continueButton(next)}
        </>
      );
      break;

    case "plan":
      title = t("start.plan.title");
      description = t("start.plan.description");
      body = (
        <>
          {catalog.isPending ? (
            <p className="text-muted-foreground text-sm">{t("start.plan.loading")}</p>
          ) : null}
          <div className="grid gap-2">
            {tiers.map((tier) => (
              <button
                key={tier.id}
                type="button"
                aria-pressed={tier === chosenTier}
                onClick={() => update({ planId: tier.id })}
                className={cn(
                  "rounded-md border p-3 text-left transition-colors hover:bg-accent",
                  tier === chosenTier && "border-primary"
                )}
              >
                <span className="flex items-baseline justify-between gap-2">
                  <span className="font-medium">{tier.name}</span>
                  <span className="font-semibold">{tier.price.display}</span>
                </span>
                <span className="mt-1 block text-muted-foreground text-sm">{tier.tagline}</span>
              </button>
            ))}
          </div>
          {continueButton(next)}
          {skipButton(() => {
            update({ planId: entryTier?.id ?? null });
            next();
          })}
        </>
      );
      break;

    case "account": {
      title = t("start.account.title");
      description = inviteLine ?? t("start.account.description");
      const formDoor = passwordLoginEnabled || keysOffered;
      body = (
        <form className="space-y-4" onSubmit={submitPassword}>
          {formDoor ? (
            <>
              {field(
                "start-email",
                t("register.emailLabel"),
                <Input
                  id="start-email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                  autoCapitalize="none"
                  required
                />
              )}
              <UsernameField
                id="start-username"
                value={username}
                onChange={setUsername}
                suggestion={slugifyUsername(answers.fullName)}
                disabled={busy}
              />
            </>
          ) : null}
          {passwordLoginEnabled ? (
            <>
              {field(
                "start-password",
                t("register.passwordLabel"),
                <Input
                  id="start-password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="new-password"
                  minLength={PASSWORD_MIN_LENGTH}
                  required
                />,
                t("passwordPolicy.minLengthHelp")
              )}
              {field(
                "start-confirm-password",
                t("register.confirmPasswordLabel"),
                <Input
                  id="start-confirm-password"
                  type="password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  autoComplete="new-password"
                  required
                />
              )}
            </>
          ) : null}
          {formDoor && captcha ? (
            <CaptchaWidget key={captchaKey} config={captcha} onToken={setCaptchaToken} />
          ) : null}
          {/* Immediately above the buttons: pressing one is the agreement. */}
          {formDoor ? <LegalNotice /> : null}
          {passwordLoginEnabled ? (
            <Button type="submit" className="w-full" disabled={busy || accountIncomplete}>
              {busy ? t("register.submitting") : t("register.submit")}
            </Button>
          ) : null}
          {keysOffered ? (
            <Button
              type="button"
              className="w-full"
              variant={passwordLoginEnabled ? "outline" : "default"}
              onClick={() => void submitPasskey()}
              disabled={busy || accountIncomplete}
            >
              {busy ? t("register.submitting") : t("register.submitPasskey")}
            </Button>
          ) : null}
          {emailOtpLoginEnabled ? (
            <Button
              type="button"
              className="w-full"
              variant={formDoor ? "ghost" : "default"}
              onClick={() => setEmailDoor(true)}
              disabled={busy || inviteBlocked}
            >
              {t("start.account.emailCode")}
            </Button>
          ) : null}
          {!formDoor && !emailOtpLoginEnabled ? (
            <p className="text-muted-foreground text-sm">{t("register.noDoorHere")}</p>
          ) : null}
        </form>
      );
      break;
    }

    case "codes":
      title = t("start.account.title");
      body = (
        <RecoveryCodesPanel
          codes={recoveryCodes}
          note={t("register.recoveryCodesNote")}
          onDone={() => commit("finishing")}
        />
      );
      break;

    case "finishing":
      title = t("start.finishing");
      body = <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden="true" />;
      break;

    case "checkEmail":
      title = held?.approval ? t("start.checkEmail.approvalTitle") : t("start.checkEmail.title");
      description = held?.approval
        ? t("start.checkEmail.approvalDescription")
        : t("start.checkEmail.description", { email: email.trim() });
      body = (
        <>
          {held?.underAge ? <p className="text-sm">{t("start.underAge")}</p> : null}
          {wantsPlan ? (
            <p className="text-sm">
              {t(portalOpens ? "start.checkEmail.planLater" : "start.planFollows")}
            </p>
          ) : null}
          <Button asChild className="w-full">
            <Link to="/login">{t("start.checkEmail.signIn")}</Link>
          </Button>
        </>
      );
      break;

    case "underAge":
      title = t("confirmAge.blockedTitle");
      description = t("start.underAge");
      body = continueButton(() => {
        if (signedIn) reset();
        else void navigate({ to: "/" });
      });
      break;

    case "people":
      title = t("start.people.title");
      description = t("start.people.description", { community: made?.name ?? finalName });
      body = made ? (
        <>
          {wantsPlan && !portalOpens ? <p className="text-sm">{t("start.planFollows")}</p> : null}
          <InviteYourPeople
            guildId={made.id}
            origin={getServerOrigin() ?? window.location.origin}
            planButton={planByButton ? () => void openPortal(made.id, "upgrade") : undefined}
            onDone={() => void leave(() => landOn(made.id, null))}
            doneLabel={t("start.people.goToCommunity", { community: made.name })}
          />
        </>
      ) : null;
      break;
  }

  return (
    <SignInFrame fillPhone>
      <Card className="grid w-full max-w-lg gap-4 p-6 shadow-lg max-sm:min-h-dvh max-sm:max-w-none max-sm:content-start max-sm:rounded-none max-sm:border-0 max-sm:pt-[max(1.5rem,env(safe-area-inset-top))] max-sm:pb-[max(1.5rem,env(safe-area-inset-bottom))]">
        <WizardFrame
          title={title}
          description={description}
          progress={
            position >= 0 && flow.length > 1
              ? { current: position + 1, total: flow.length }
              : undefined
          }
          onBack={canGoBack && !busy ? back : undefined}
          backLabel={t("common:back")}
        >
          {body}
          {error ? (
            <p className="text-destructive text-sm" role="alert">
              {error}
            </p>
          ) : null}
          {footer}
        </WizardFrame>
      </Card>
    </SignInFrame>
  );
};

/** The new community's first invite link, to copy and send. */
const InviteYourPeople = ({
  guildId,
  origin,
  planButton,
  onDone,
  doneLabel,
}: {
  guildId: number;
  origin: string;
  /** Shown when a plan was picked but its tab could not be opened. */
  planButton?: () => void;
  onDone: () => void;
  doneLabel: string;
}) => {
  const { t } = useTranslation(["auth", "common", "guilds"]);
  const [link, setLink] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const asked = useRef(false);

  useEffect(() => {
    if (asked.current) return;
    asked.current = true;
    // One link for the whole group, so it takes any number of people.
    createGuildInviteApiV1CommunitiesGuildIdInvitesPost(guildId, { max_uses: null })
      .then((invite) => setLink(`${origin}/invite/${encodeURIComponent(invite.code)}`))
      .catch(() => setFailed(true));
  }, [guildId, origin]);

  const copy = async () => {
    if (!link) return;
    await navigator.clipboard.writeText(link);
    toast.success(t("guilds:inviteLinkCopied"));
  };

  return (
    <>
      {failed ? (
        <p className="text-muted-foreground text-sm">{t("start.people.linkError")}</p>
      ) : (
        <div className="space-y-2">
          <Label htmlFor="start-invite-link">{t("start.people.linkLabel")}</Label>
          <div className="flex gap-2">
            <Input id="start-invite-link" value={link ?? ""} readOnly />
            <Button type="button" variant="outline" onClick={() => void copy()} disabled={!link}>
              {t("common:copy")}
            </Button>
          </div>
        </div>
      )}
      {planButton ? (
        <Button type="button" variant="outline" className="w-full" onClick={planButton}>
          {t("start.people.choosePlan")}
        </Button>
      ) : null}
      <Button type="button" className="w-full" onClick={onDone}>
        {doneLabel}
      </Button>
    </>
  );
};
