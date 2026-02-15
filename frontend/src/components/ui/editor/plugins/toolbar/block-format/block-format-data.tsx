import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  CodeIcon,
  Heading1Icon,
  Heading2Icon,
  Heading3Icon,
  ListIcon,
  ListOrderedIcon,
  ListTodoIcon,
  QuoteIcon,
  TextIcon,
} from "lucide-react";

export type BlockFormatEntry = { label: string; icon: React.ReactNode };

export function useBlockTypeToBlockName(): Record<string, BlockFormatEntry> {
  const { t } = useTranslation("documents");
  return useMemo(
    () => ({
      paragraph: {
        label: t("editor.blockNormal"),
        icon: <TextIcon className="size-4" />,
      },
      h1: {
        label: t("editor.blockH1"),
        icon: <Heading1Icon className="size-4" />,
      },
      h2: {
        label: t("editor.blockH2"),
        icon: <Heading2Icon className="size-4" />,
      },
      h3: {
        label: t("editor.blockH3"),
        icon: <Heading3Icon className="size-4" />,
      },
      number: {
        label: t("editor.numberedList"),
        icon: <ListOrderedIcon className="size-4" />,
      },
      bullet: {
        label: t("editor.bulletedList"),
        icon: <ListIcon className="size-4" />,
      },
      check: {
        label: t("editor.checklist"),
        icon: <ListTodoIcon className="size-4" />,
      },
      code: {
        label: t("editor.blockCode"),
        icon: <CodeIcon className="size-4" />,
      },
      quote: {
        label: t("editor.blockQuote"),
        icon: <QuoteIcon className="size-4" />,
      },
    }),
    [t]
  );
}
