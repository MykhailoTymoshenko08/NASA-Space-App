import s from "./compare.module.css";

/** Round letter (A to D) that ties a field's card, table column and verdicts together. Decorative: pair it with text. */
export function FieldLetter({ label, size = "md" }: { label: string; size?: "sm" | "md" }) {
  return (
    <span className={`${s.letter} ${size === "sm" ? s.letterSm : ""}`} aria-hidden="true">
      {label}
    </span>
  );
}
