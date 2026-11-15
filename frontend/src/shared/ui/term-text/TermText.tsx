import {
  createContext,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FocusEvent,
  type ReactNode,
} from "react";
import s from "./term-text.module.css";

/** One explained term: what running text matches, what the popover says, and where "Learn more" goes. */
export type TermEntry = {
  /** Element id of the full entry on the page; "Learn more" links to `#id`. */
  id: string;
  /** Title in the popover. */
  term: string;
  /** What it is. */
  def: string;
  /** Why it matters. */
  why: string;
  /**
   * Phrases that count as this term in running text. Matching ignores case, except for phrases with
   * capitals past the first letter: one word ("NDVI", "pH") matches exactly, several words ("soil pH")
   * match exactly apart from the first letter.
   */
  match: readonly string[];
};

type Matcher = {
  regex: RegExp;
  byPhrase: ReadonlyMap<string, { phrase: string; entry: TermEntry }>;
};

type Piece = string | { text: string; entry: TermEntry };

const TermsContext = createContext<Matcher | null>(null);

const escapeRe = (t: string) => t.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");

function buildMatcher(terms: readonly TermEntry[]): Matcher | null {
  const byPhrase = new Map<string, { phrase: string; entry: TermEntry }>();
  for (const entry of terms) {
    for (const phrase of entry.match) {
      const key = phrase.toLowerCase();
      if (phrase.trim() && !byPhrase.has(key)) byPhrase.set(key, { phrase, entry });
    }
  }
  if (byPhrase.size === 0) return null;
  // Longest first, so "soil moisture anomaly" wins over "anomaly".
  const alts = [...byPhrase.values()]
    .map((p) => p.phrase)
    .sort((a, b) => b.length - a.length)
    .map(escapeRe);
  // Whole words only: no letter or digit right before or after the phrase.
  return { regex: new RegExp(`(?<![\\p{L}\\p{N}])(?:${alts.join("|")})(?![\\p{L}\\p{N}])`, "giu"), byPhrase };
}

/**
 * "ET" must not match "et" and "pH" must not match "PH" (one word with capitals: exact case), while
 * "Soil pH" at a sentence start may match "soil pH" (several words: only the first letter's case is free).
 */
function caseFits(found: string, phrase: string): boolean {
  const rest = phrase.slice(1);
  if (rest === rest.toLowerCase()) return true;
  return /\s/.test(phrase) ? found.slice(1) === rest : found === phrase;
}

function splitTerms(text: string, matcher: Matcher): Piece[] {
  const out: Piece[] = [];
  let last = 0;
  for (const m of text.matchAll(matcher.regex)) {
    const hit = matcher.byPhrase.get(m[0].toLowerCase());
    if (!hit || !caseFits(m[0], hit.phrase)) continue;
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    out.push({ text: m[0], entry: hit.entry });
    last = at + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** Makes the terms available to every `TermText` below it. */
export function TermsProvider({ terms, children }: { terms: readonly TermEntry[]; children: ReactNode }) {
  const matcher = useMemo(() => buildMatcher(terms), [terms]);
  return <TermsContext.Provider value={matcher}>{children}</TermsContext.Provider>;
}

/**
 * Plain text with every known term marked. Hover, focus or tap a term for a short popover with what it
 * is, why it matters and a "Learn more" link to the full entry. Without a `TermsProvider` it is plain text.
 */
export function TermText({ children }: { children: string }) {
  const matcher = useContext(TermsContext);
  const pieces = useMemo(() => (matcher ? splitTerms(children, matcher) : [children]), [children, matcher]);
  return (
    <>
      {pieces.map((p, i) => (typeof p === "string" ? p : <Term key={i} text={p.text} entry={p.entry} />))}
    </>
  );
}

const CLOSE_DELAY_MS = 150;
const GAP = 8;
const EDGE = 16;

function Term({ text, entry }: { text: string; entry: TermEntry }) {
  const [open, setOpen] = useState(false);
  const popId = useId();
  const wrapRef = useRef<HTMLSpanElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLSpanElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // Focus returned to the button by Escape must not reopen the popover.
  const skipFocusOpen = useRef(false);

  const show = () => {
    clearTimeout(closeTimer.current);
    setOpen(true);
  };
  const hideSoon = () => {
    clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setOpen(false), CLOSE_DELAY_MS);
  };
  useEffect(() => () => clearTimeout(closeTimer.current), []);

  // Fixed position next to the term, kept inside the viewport; flips above when there is no room below.
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const btn = btnRef.current;
      const pop = popRef.current;
      if (!btn || !pop) return;
      const r = btn.getBoundingClientRect();
      const vw = document.documentElement.clientWidth || window.innerWidth;
      const vh = window.innerHeight;
      const left = Math.max(EDGE, Math.min(r.left, vw - pop.offsetWidth - EDGE));
      const below = r.bottom + GAP;
      const above = r.top - GAP - pop.offsetHeight;
      const top = below + pop.offsetHeight > vh - EDGE && above > EDGE ? above : below;
      pop.style.left = `${left}px`;
      pop.style.top = `${top}px`;
    };
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open]);

  // Escape closes; a tap outside closes (touch screens have no mouse leave).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      clearTimeout(closeTimer.current);
      setOpen(false);
      if (wrapRef.current?.contains(document.activeElement) && document.activeElement !== btnRef.current) {
        skipFocusOpen.current = true;
        btnRef.current?.focus();
      }
    };
    const onDown = (e: PointerEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
    };
  }, [open]);

  const onFocus = () => {
    if (skipFocusOpen.current) {
      skipFocusOpen.current = false;
      return;
    }
    show();
  };
  const onBlur = (e: FocusEvent) => {
    if (!wrapRef.current?.contains(e.relatedTarget as Node | null)) setOpen(false);
  };

  return (
    <span ref={wrapRef} className={s.wrap} onMouseEnter={show} onMouseLeave={hideSoon} onFocus={onFocus} onBlur={onBlur}>
      <button
        ref={btnRef}
        type="button"
        className={s.term}
        aria-expanded={open}
        aria-controls={open ? popId : undefined}
        onClick={show}
      >
        {text}
      </button>
      {open && (
        <span ref={popRef} id={popId} role="note" aria-label={entry.term} className={s.pop}>
          <span className={s.popTitle}>{entry.term}</span>
          <span className={s.popText}>{entry.def}</span>
          <span className={s.popText}>
            <strong>Why it matters.</strong> {entry.why}
          </span>
          <a href={`#${entry.id}`} className={s.popLink} onClick={() => setOpen(false)}>
            Learn more in the glossary
          </a>
        </span>
      )}
    </span>
  );
}
