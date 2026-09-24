/**
 * The scopes an app asks a community for, as the seat chooses them.
 *
 * Shared by the install dialog and the scopes panel, so both tick the same way
 * and say the same thing about each scope.
 */

import type { TFunction } from "i18next";

import { TOOLS, toolCamelPlural, toolPlural } from "@/lib/tools";

export type ScopeAccess = "read" | "write";

/** A `t` holding the `apps` and `nav` namespaces, whatever else it holds. */
export type ScopeT = TFunction<any>;

/** A scope split into the resource it names and the access it gives. */
export const parseScope = (scope: string): { resource: string; access: ScopeAccess } => {
  const [resource, access] = scope.split(":") as [string, ScopeAccess];
  return { resource, access };
};

const scopeOf = (resource: string, access: ScopeAccess) => `${resource}:${access}`;

/**
 * The chosen set after ticking or unticking one scope.
 *
 * Changing implies reading: ticking a change ticks the read too when it can be
 * granted, and unticking the read takes the change with it. Only scopes in
 * `grantable` are ever added.
 */
export const toggleScope = (
  chosen: string[],
  scope: string,
  on: boolean,
  grantable: ReadonlySet<string>
): string[] => {
  const { resource, access } = parseScope(scope);
  const read = scopeOf(resource, "read");
  const write = scopeOf(resource, "write");
  let next = chosen.filter((one) => one !== scope);
  if (on) {
    if (grantable.has(scope)) next.push(scope);
    if (access === "write" && grantable.has(read)) next.push(read);
  } else if (access === "read") {
    next = next.filter((one) => one !== write);
  }
  return [...new Set(next)];
};

/** The name a resource goes by, from the tool's own label where it is a tool. */
export const scopeResourceLabel = (resource: string, t: ScopeT): string => {
  const tool = TOOLS.find((one) => toolPlural(one) === resource);
  return tool
    ? t(`nav:${toolCamelPlural(tool)}` as never)
    : t(`apps:scopes.resources.${resource}` as never);
};

/**
 * What granting a scope lets the app do, as a plain sentence: "Read and change
 * projects", "See who is in your community". A resource with no sentence of its
 * own is said with its label.
 */
export const scopeSentence = (scope: string, t: ScopeT): string => {
  const { resource, access } = parseScope(scope);
  return t(`apps:scopes.sentences.${resource}.${access}` as never, {
    defaultValue: t(`apps:scopes.sentences.fallback.${access}` as never, {
      resource: scopeResourceLabel(resource, t),
    }),
  });
};
