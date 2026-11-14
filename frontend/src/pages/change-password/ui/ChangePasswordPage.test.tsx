import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { getSession, signIn, signOut, signUp } from "@/entities/session";
import { renderRoutes } from "@/shared/lib/test";
import { handlers } from "@/shared/mocks";
import { ChangePasswordPage } from "./ChangePasswordPage";

const server = setupServer(...handlers);
beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(async () => {
  localStorage.clear();
  sessionStorage.clear();
  await signOut();
});

const EMAIL = "grower@example.com";
const OLD_PASSWORD = "original123";
const NEW_PASSWORD = "replacement456";
const renderPage = () =>
  renderRoutes([
    { path: "/account/password", element: <ChangePasswordPage /> },
    { path: "/sign-in", element: <p>Sign in page</p> },
  ], "/account/password");

async function fill(current: string, next = NEW_PASSWORD, repeat = next) {
  await userEvent.type(screen.getByLabelText("Current password"), current);
  await userEvent.type(screen.getByLabelText("New password"), next);
  await userEvent.type(screen.getByLabelText("Repeat the new password"), repeat);
  await userEvent.click(screen.getByRole("button", { name: "Change password" }));
}

describe("change password page", () => {
  it("asks a signed-out visitor to sign in", () => {
    renderPage();
    expect(screen.getByText("Sign in first to change your password.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      `/sign-in?next=${encodeURIComponent("/account/password")}`,
    );
  });

  it("validates locally before calling the API", async () => {
    await signUp({ email: EMAIL, password: OLD_PASSWORD });
    renderPage();
    await fill(OLD_PASSWORD, "short", "different");
    expect(screen.getByText("Use at least 8 characters with one letter and one number.")).toBeInTheDocument();
    expect(screen.getByText("The two passwords do not match.")).toBeInTheDocument();
    expect(getSession().status).toBe("authenticated");
  });

  it("shows a wrong current password on its field and keeps the session", async () => {
    await signUp({ email: EMAIL, password: OLD_PASSWORD });
    renderPage();
    await fill("wrong1234");
    expect(await screen.findByText("Your current password is not right.")).toBeInTheDocument();
    expect(getSession().status).toBe("authenticated");
  });

  it("changes the password, signs out, and needs the new password to sign in", async () => {
    await signUp({ email: EMAIL, password: OLD_PASSWORD });
    renderPage();
    await fill(OLD_PASSWORD);
    expect(await screen.findByRole("heading", { name: "Password changed" })).toBeInTheDocument();
    expect(getSession().status).toBe("anonymous");
    await expect(signIn({ email: EMAIL, password: OLD_PASSWORD, remember: true })).rejects.toMatchObject({ status: 401 });
    await expect(signIn({ email: EMAIL, password: NEW_PASSWORD, remember: true })).resolves.toMatchObject({ email: EMAIL });
  });
});
