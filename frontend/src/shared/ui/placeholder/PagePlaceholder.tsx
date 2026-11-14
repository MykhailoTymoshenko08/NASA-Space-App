import { useEffect, type ReactNode } from "react";
import { APP_NAME } from "@/shared/config";
import { Container } from "../layout";
import s from "./placeholder.module.css";

/** Simple page frame for routes that exist but are not built yet. */
export function PagePlaceholder({ title, children }: { title: string; children?: ReactNode }) {
  useEffect(() => {
    document.title = `${title} · ${APP_NAME}`;
  }, [title]);

  return (
    <Container as="section" className={s.wrap} aria-labelledby="placeholder-title">
      <h1 id="placeholder-title" className={s.title}>
        {title}
      </h1>
      <div className={s.body}>{children}</div>
    </Container>
  );
}
