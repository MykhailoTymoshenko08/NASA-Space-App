import type { ElementType, HTMLAttributes, ReactNode } from "react";
import { ButtonLink } from "../button";
import { Icon } from "../icon";
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

/** Larger surface block (radius 16), stacks its children with a gap. */
export function Panel({
  as: Tag = "div",
  className,
  gap = 12,
  ...rest
}: Props & { gap?: 4 | 8 | 12 | 14 | 16 | 20 }) {
  return <Tag className={join(s.panel, className)} style={{ gap }} {...rest} />;
}

export function Eyebrow({ as: Tag = "p", className, ...rest }: Props) {
  return <Tag className={join(s.eyebrow, className)} {...rest} />;
}

export function MonoLabel({ as: Tag = "div", className, ...rest }: Props) {
  return <Tag className={join(s.monoLabel, className)} {...rest} />;
}

/** Page head: optional back link, the h1 and a lead line. */
export function PageIntro({
  title,
  lead,
  back,
  titleId = "page-title",
}: {
  title: ReactNode;
  lead?: ReactNode;
  back?: { to: string; label: string };
  titleId?: string;
}) {
  return (
    <Container as="section" className={s.intro} aria-labelledby={titleId}>
      {back && (
        <ButtonLink to={back.to} variant="link" className={s.back}>
          <Icon name="arrow-left" size={18} />
          {back.label}
        </ButtonLink>
      )}
      <h1 id={titleId} className={s.title}>
        {title}
      </h1>
      {lead && <p className={s.lead}>{lead}</p>}
    </Container>
  );
}

/** Two columns that wrap: a wide main column and a 320 to 400 px aside. */
export function PageColumns({ main, aside, asideLabel }: { main: ReactNode; aside: ReactNode; asideLabel: string }) {
  return (
    <Container className={s.columns}>
      <div className={s.main}>{main}</div>
      <aside className={s.aside} aria-label={asideLabel}>
        {aside}
      </aside>
    </Container>
  );
}

/** Centered 480 px card for short forms (sign in, create account, reset password). */
export function FormCard({ title, lead, children }: { title: string; lead?: ReactNode; children: ReactNode }) {
  return (
    <section className={s.formWrap} aria-labelledby="page-title">
      <div className={s.formCard}>
        <div className={s.formHead}>
          <h1 id="page-title" className={s.formTitle}>
            {title}
          </h1>
          {lead && <p className={s.formLead}>{lead}</p>}
        </div>
        {children}
      </div>
    </section>
  );
}

/** Section title (24 px display). */
export function SectionTitle({ as: Tag = "h2", className, ...rest }: Props) {
  return <Tag className={join(s.sectionTitle, className)} {...rest} />;
}
