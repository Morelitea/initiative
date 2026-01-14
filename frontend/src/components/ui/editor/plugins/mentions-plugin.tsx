import { JSX, lazy, Suspense, useCallback, useMemo, useState } from "react";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import {
  MenuOption,
  MenuTextMatch,
  useBasicTypeaheadTriggerMatch,
} from "@lexical/react/LexicalTypeaheadMenuPlugin";
import { TextNode } from "lexical";
import { createPortal } from "react-dom";

import { $createMentionNode } from "@/components/ui/editor/nodes/mention-node";
import { Command, CommandGroup, CommandItem, CommandList } from "@/components/ui/command";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import type { UserPublic } from "@/types/api";

const LexicalTypeaheadMenuPlugin = lazy(() =>
  import("@lexical/react/LexicalTypeaheadMenuPlugin").then((mod) => ({
    default: mod.LexicalTypeaheadMenuPlugin<MentionTypeaheadOption>,
  }))
);

const PUNCTUATION = "\\.,\\+\\*\\?\\$\\@\\|#{}\\(\\)\\^\\-\\[\\]\\\\/!%'\"~=<>_:;";
const NAME = "\\b[A-Z][^\\s" + PUNCTUATION + "]";

const DocumentMentionsRegex = {
  NAME,
  PUNCTUATION,
};

const PUNC = DocumentMentionsRegex.PUNCTUATION;

const TRIGGERS = ["@"].join("");

// Chars we expect to see in a mention (non-space, non-punctuation).
const VALID_CHARS = "[^" + TRIGGERS + PUNC + "\\s]";

// Non-standard series of chars. Each series must be preceded and followed by
// a valid char.
const VALID_JOINS =
  "(?:" +
  "\\.[ |$]|" + // E.g. "r. " in "Mr. Smith"
  " |" + // E.g. " " in "Josh Duck"
  "[" +
  PUNC +
  "]|" + // E.g. "-' in "Salier-Hellendag"
  ")";

const LENGTH_LIMIT = 75;

const AtSignMentionsRegex = new RegExp(
  "(^|\\s|\\()(" +
    "[" +
    TRIGGERS +
    "]" +
    "((?:" +
    VALID_CHARS +
    VALID_JOINS +
    "){0," +
    LENGTH_LIMIT +
    "})" +
    ")$"
);

// 50 is the longest alias length limit.
const ALIAS_LENGTH_LIMIT = 50;

// Regex used to match alias.
const AtSignMentionsRegexAliasRegex = new RegExp(
  "(^|\\s|\\()(" +
    "[" +
    TRIGGERS +
    "]" +
    "((?:" +
    VALID_CHARS +
    "){0," +
    ALIAS_LENGTH_LIMIT +
    "})" +
    ")$"
);

// At most, 5 suggestions are shown in the popup.
const SUGGESTION_LIST_LENGTH_LIMIT = 5;

function checkForAtSignMentions(text: string, minMatchLength: number): MenuTextMatch | null {
  let match = AtSignMentionsRegex.exec(text);

  if (match === null) {
    match = AtSignMentionsRegexAliasRegex.exec(text);
  }
  if (match !== null) {
    // The strategy ignores leading whitespace but we need to know it's
    // length to add it to the leadOffset

    const maybeLeadingWhitespace = match[1];

    const matchingString = match[3];
    if (matchingString.length >= minMatchLength) {
      return {
        leadOffset: match.index + maybeLeadingWhitespace.length,
        matchingString,
        replaceableString: match[2],
      };
    }
  }
  return null;
}

function getPossibleQueryMatch(text: string): MenuTextMatch | null {
  return checkForAtSignMentions(text, 0);
}

function getDisplayName(user: UserPublic): string {
  return user.full_name?.trim() || user.email;
}

function getInitials(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

class MentionTypeaheadOption extends MenuOption {
  name: string;
  userId: number;
  picture: JSX.Element;

  constructor(name: string, userId: number, picture: JSX.Element) {
    super(name);
    this.name = name;
    this.userId = userId;
    this.picture = picture;
  }
}

function useMentionLookupService(
  queryString: string | null,
  users: UserPublic[]
): MentionTypeaheadOption[] {
  return useMemo(() => {
    if (queryString === null) {
      return [];
    }
    const lowerQuery = queryString.toLowerCase();
    return users
      .filter((user) => {
        const name = getDisplayName(user).toLowerCase();
        const email = user.email.toLowerCase();
        return name.includes(lowerQuery) || email.includes(lowerQuery);
      })
      .slice(0, SUGGESTION_LIST_LENGTH_LIMIT)
      .map((user) => {
        const displayName = getDisplayName(user);
        const avatarSrc = user.avatar_url || user.avatar_base64 || undefined;
        const initials = getInitials(displayName);
        return new MentionTypeaheadOption(
          displayName,
          user.id,
          (
            <Avatar className="h-5 w-5 text-[10px]">
              {avatarSrc ? <AvatarImage src={avatarSrc} alt={displayName} /> : null}
              <AvatarFallback>{initials}</AvatarFallback>
            </Avatar>
          )
        );
      });
  }, [queryString, users]);
}

export interface MentionsPluginProps {
  mentionableUsers?: UserPublic[];
}

export function MentionsPlugin({ mentionableUsers = [] }: MentionsPluginProps): JSX.Element | null {
  const [editor] = useLexicalComposerContext();

  const [queryString, setQueryString] = useState<string | null>(null);

  const options = useMentionLookupService(queryString, mentionableUsers);

  const checkForSlashTriggerMatch = useBasicTypeaheadTriggerMatch("/", {
    minLength: 0,
  });

  const onSelectOption = useCallback(
    (
      selectedOption: MentionTypeaheadOption,
      nodeToReplace: TextNode | null,
      closeMenu: () => void
    ) => {
      editor.update(() => {
        const mentionNode = $createMentionNode(selectedOption.name, selectedOption.userId);
        if (nodeToReplace) {
          nodeToReplace.replace(mentionNode);
        }
        mentionNode.select();
        closeMenu();
      });
    },
    [editor]
  );

  const checkForMentionMatch = useCallback(
    (text: string) => {
      const slashMatch = checkForSlashTriggerMatch(text, editor);
      if (slashMatch !== null) {
        return null;
      }
      return getPossibleQueryMatch(text);
    },
    [checkForSlashTriggerMatch, editor]
  );

  if (mentionableUsers.length === 0) {
    return null;
  }

  return (
    <Suspense fallback={null}>
      <LexicalTypeaheadMenuPlugin
        onQueryChange={setQueryString}
        onSelectOption={onSelectOption}
        triggerFn={checkForMentionMatch}
        options={options}
        menuRenderFn={(
          anchorElementRef,
          { selectedIndex, selectOptionAndCleanUp, setHighlightedIndex }
        ) => {
          return anchorElementRef.current && options.length
            ? createPortal(
                <div className="fixed z-10 w-[250px] rounded-md shadow-md">
                  <Command
                    onKeyDown={(e) => {
                      if (e.key === "ArrowUp") {
                        e.preventDefault();
                        setHighlightedIndex(
                          selectedIndex !== null
                            ? (selectedIndex - 1 + options.length) % options.length
                            : options.length - 1
                        );
                      } else if (e.key === "ArrowDown") {
                        e.preventDefault();
                        setHighlightedIndex(
                          selectedIndex !== null ? (selectedIndex + 1) % options.length : 0
                        );
                      }
                    }}
                  >
                    <CommandList>
                      <CommandGroup>
                        {options.map((option, index) => (
                          <CommandItem
                            key={option.key}
                            value={option.name}
                            onSelect={() => {
                              selectOptionAndCleanUp(option);
                            }}
                            className={`flex items-center gap-2 ${
                              selectedIndex === index ? "bg-accent" : "bg-transparent!"
                            }`}
                          >
                            {option.picture}
                            <span className="truncate">{option.name}</span>
                          </CommandItem>
                        ))}
                      </CommandGroup>
                    </CommandList>
                  </Command>
                </div>,
                anchorElementRef.current
              )
            : null;
        }}
      />
    </Suspense>
  );
}
