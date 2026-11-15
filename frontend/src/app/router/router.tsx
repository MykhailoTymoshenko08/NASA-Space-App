import { createBrowserRouter } from "react-router";
import { AnalysisPage, AnalysisSetupPage } from "@/pages/analysis";
import { ChangePasswordPage } from "@/pages/change-password";
import { FieldPage } from "@/pages/field";
import { MyFieldsPage } from "@/pages/my-fields";
import { NotFoundPage } from "@/pages/not-found";
import { ResetPasswordPage } from "@/pages/reset-password";
import { SignInPage } from "@/pages/sign-in";
import { SignUpPage } from "@/pages/sign-up";
import { ROUTES } from "@/shared/config";
import { RootLayout } from "../layout/RootLayout";
import { resetEntryScroll } from "./entry-scroll";

resetEntryScroll();

/** Route table only. Every screen lives in src/pages. Map pages load lazily (MapLibre is large). */
export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      { path: ROUTES.home, lazy: () => import("@/pages/landing").then((m) => ({ Component: m.LandingPage })) },
      { path: ROUTES.pickField, lazy: () => import("@/pages/pick-field").then((m) => ({ Component: m.PickFieldPage })) },
      { path: ROUTES.field, element: <FieldPage /> },
      { path: ROUTES.analysisSetup, element: <AnalysisSetupPage /> },
      { path: ROUTES.analysis, element: <AnalysisPage /> },
      { path: ROUTES.signIn, element: <SignInPage /> },
      { path: ROUTES.signUp, element: <SignUpPage /> },
      { path: ROUTES.resetPassword, element: <ResetPasswordPage /> },
      { path: ROUTES.myFields, element: <MyFieldsPage /> },
      { path: ROUTES.areaRanking, lazy: () => import("@/pages/area-ranking").then((m) => ({ Component: m.AreaRankingPage })) },
      { path: ROUTES.changePassword, element: <ChangePasswordPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
