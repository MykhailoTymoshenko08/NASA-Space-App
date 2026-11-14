import type { ElementType, HTMLAttributes, ReactNode } from "react";
import s from "./layout.module.css";

type Props = HTMLAttributes<HTMLElement> & { as?: ElementType; children: ReactNode };

const join = (...c: (string | undefined | false)[]) => c.filter(Boolean).join(" ");

/** Centered 1280 px column with the page gutter. */
export function Container({ as: Tag = "div", className, ...rest }: Props) {
  return <Tag className={join(s.container, className)} {...rest} />;
}

/** Surface card with a hairline border (radius 14). */
export function Card({ as: Tag = "div", className, compact, ...rest }: Props & { compact?: boolean }) {
  return <Tag className={join(s.card, compact && s.cardCompact, className)} {...rest} />;
}

export function Eyebrow({ as: Tag = "p", className, ...rest }: Props) {
  return <Tag className={join(s.eyebrow, className)} {...rest} />;
}

export function MonoLabel({ as: Tag = "div", className, ...rest }: Props) {
  return <Tag className={join(s.monoLabel, className)} {...rest} />;
}
