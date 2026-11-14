import { APP_NAME } from "@/shared/config";
import s from "./site-footer.module.css";

export function SiteFooter() {
  return (
    <footer className={s.footer}>
      <span>{APP_NAME} is a working name. Replace it with your brand.</span>
      <span>Base data: NASA POWER, SMAP and HLS. Final list set by the data science team.</span>
    </footer>
  );
}
