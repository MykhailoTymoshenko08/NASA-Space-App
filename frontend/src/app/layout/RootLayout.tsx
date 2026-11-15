import { Outlet, ScrollRestoration, useNavigation } from "react-router";
import { env } from "@/shared/config";
import { RouteProgress } from "@/shared/ui/page-loader";
import { SiteHeader } from "@/widgets/site-header";
import s from "./root-layout.module.css";

export function RootLayout() {
  const navigation = useNavigation();
  const loading = navigation.state === "loading";

  return (
    <>
      <RouteProgress active={loading} />
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      {env.useMocks && (
        <div className={s.mockBanner} role="note" data-mock-banner>
          Demo mode: every value on screen comes from mock data, not from our server.
        </div>
      )}
      <SiteHeader />
      <main id="main" tabIndex={-1} className={s.main} aria-busy={loading || undefined}>
        <Outlet />
      </main>
      <ScrollRestoration />
    </>
  );
}
