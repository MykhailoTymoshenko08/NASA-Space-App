import { Outlet, ScrollRestoration } from "react-router";
import { env } from "@/shared/config";
import { SiteHeader } from "@/widgets/site-header";
import s from "./root-layout.module.css";

export function RootLayout() {
  return (
    <>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      {env.useMocks && (
        <div className={s.mockBanner} role="note" data-mock-banner>
          Demo mode: every value on screen comes from mock data, not from our server.
        </div>
      )}
      <SiteHeader />
      <main id="main" tabIndex={-1} className={s.main}>
        <Outlet />
      </main>
      <ScrollRestoration />
    </>
  );
}
