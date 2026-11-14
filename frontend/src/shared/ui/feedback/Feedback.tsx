import type { CSSProperties, ReactNode } from "react";
import { Icon, type IconName } from "../icon";
import s from "./feedback.module.css";

export type Tone = "success" | "info" | "error" | "neutral";

/** Status pill. Text always carries the meaning; color only supports it. */
export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`${s.badge} ${s[tone]}`}>{children}</span>;
}

const MESSAGE_ICON: Record<Exclude<Tone, "neutral">, IconName> = {
  success: "check",
  info: "info",
  error: "warning",
};

/** Icon + sentence on a tinted ground (DS "Messages"). */
export function Message({
  tone,
  children,
  role,
}: {
  tone: Exclude<Tone, "neutral">;
  children: ReactNode;
  role?: "status" | "alert";
}) {
  return (
    <div className={`${s.message} ${s[tone]}`} role={role}>
      <Icon name={MESSAGE_ICON[tone]} />
      <div className={s.messageBody}>{children}</div>
    </div>
  );
}

/** Loading placeholder block. Hidden from screen readers; announce loading with text nearby. */
export function Skeleton({ width = "100%", height, soft }: { width?: CSSProperties["width"]; height: number; soft?: boolean }) {
  return <span aria-hidden="true" className={`${s.skeleton} ${soft ? s.skeletonSoft : ""}`} style={{ width, height }} />;
}
