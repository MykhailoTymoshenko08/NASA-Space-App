import { useEffect } from "react";
import { APP_NAME } from "@/shared/config";

/** Sets the tab title as "<title> · <app name>". */
export function useDocumentTitle(title: string) {
  useEffect(() => {
    document.title = `${title} · ${APP_NAME}`;
  }, [title]);
}
