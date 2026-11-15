import type { ReactNode } from "react";
import { TermsProvider } from "@/shared/ui/term-text";
import { GLOSSARY } from "../lib/glossary";

/**
 * Marks every glossary term in the `TermText` below it with a hover popover and a "Learn more" link to its
 * entry in `Glossary`. Wrap only pages that also render `Glossary`, so the link has somewhere to go.
 */
export function GlossaryTerms({ children }: { children: ReactNode }) {
  return <TermsProvider terms={GLOSSARY}>{children}</TermsProvider>;
}
