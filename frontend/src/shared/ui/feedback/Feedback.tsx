import type { CSSProperties, ReactNode } from "react";
import { Icon, type IconName } from "../icon";
import s from "./feedback.module.css";

export type Tone = "success" | "info" | "warning" | "error" | "neutral";

/** Status pill. Text always carries the meaning; color only supports it. */
export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`${s.badge} ${s[tone]}`}>{children}</span>;
}

const MESSAGE_ICON: Record<Exclude<Tone, "neutral">, IconName> = {
  success: "check",
  info: "info",
  warning: "warning",
  error: "warning",
};

/** Icon + sentence on a tinted ground (DS "Messages"). */
export function Message({
  tone,
  children,
  role,
  id,
}: {
  tone: Exclude<Tone, "neutral">;
  children: ReactNode;
  role?: "status" | "alert";
  id?: string;
}) {
  return (
    <div className={`${s.message} ${s[tone]}`} role={role} id={id}>
      <Icon name={MESSAGE_ICON[tone]} />
      <div className={s.messageBody}>{children}</div>
    </div>
  );
}

/** Larger note block (radius 14): "Keep in mind", disclaimers, boundary notes. */
export function Note({
  tone = "neutral",
  title,
  children,
  role = "note",
}: {
  tone?: "neutral" | "warning";
  title?: ReactNode;
  children: ReactNode;
  role?: "note" | "status";
}) {
  return (
    <div className={`${s.note} ${tone === "warning" ? s.noteWarning : ""}`} role={role}>
      <Icon name={tone === "warning" ? "warning" : "info"} size={22} />
      <div className={s.noteBody}>
        {title && <strong>{title}</strong>}
        {children}
      </div>
    </div>
  );
}

/** Blocking error for a whole section: red 2 px border, title, message, code and actions. */
export function ErrorPanel({
  title,
  message,
  code,
  requestId,
  actions,
}: {
  title: string;
  message: ReactNode;
  code?: string | null;
  requestId?: string | null;
  actions?: ReactNode;
}) {
  return (
    <div className={s.errorPanel} role="alert">
      <div className={s.errorHead}>
        <Icon name="warning" size={22} />
        <h2 className={s.errorTitle}>{title}</h2>
      </div>
      <p>{message}</p>
      {(code || requestId) && (
        <div className={s.code}>
          {code}
          {code && requestId ? " · " : ""}
          {requestId && `Request ID: ${requestId}`}
        </div>
      )}
      {actions && <div className={s.actions}>{actions}</div>}
    </div>
  );
}

/** Loading placeholder block. Hidden from screen readers; announce loading with text nearby. */
export function Skeleton({ width = "100%", height, soft }: { width?: CSSProperties["width"]; height: number; soft?: boolean }) {
  return <span aria-hidden="true" className={`${s.skeleton} ${soft ? s.skeletonSoft : ""}`} style={{ width, height }} />;
}
