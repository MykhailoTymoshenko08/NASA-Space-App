import { createBrowserRouter } from "react-router";
import { AnalysisPage } from "@/pages/analysis";
import { FieldPage } from "@/pages/field";
import { LandingPage } from "@/pages/landing";
import { NotFoundPage } from "@/pages/not-found";
import { PickFieldPage } from "@/pages/pick-field";
import { SignInPage } from "@/pages/sign-in";
import { ROUTES } from "@/shared/config";
import { RootLayout } from "../layout/RootLayout";

/** Route table only. Every screen lives in src/pages. */
export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      { path: ROUTES.home, element: <LandingPage /> },
      { path: ROUTES.pickField, element: <PickFieldPage /> },
      { path: ROUTES.field, element: <FieldPage /> },
      { path: ROUTES.analysis, element: <AnalysisPage /> },
      { path: ROUTES.signIn, element: <SignInPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
