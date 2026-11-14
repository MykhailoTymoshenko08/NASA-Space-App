import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { changePassword, getSession, signIn, signOut, signUp } from "@/entities/session";
import { passwordResetApi } from "@/features/reset-password";
import { renderRoutes } from "@/shared/lib/test";
import { handlers } from "@/shared/mocks";
import { ResetPasswordPage } from "./ResetPasswordPage";

const server = setupServer(...handlers);
beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(async () => {
  localStorage.clear();
  sessionStorage.clear();
  await signOut();
});

const EMAIL = "farmer@example.com";
const OLD_PASSWORD = "original123";
const NEW_PASSWORD = "replacement456";
const renderAt = (url: string) => renderRoutes([
  { path: "/reset-password", element: <ResetPasswordPage /> },
  { path: "/sign-in", element: <p>Sign in page</p> },
], url);

async function submitPassword(password = NEW_PASSWORD) {
  await userEvent.type(screen.getByLabelText("New password"), password);
  await userEvent.type(screen.getByLabelText("Repeat the new password"), password);
  await userEvent.click(screen.getByRole("button", { name: "Save new password" }));
}

describe("password recovery", () => {
  it.each([true, false])("shows the same email confirmation when account exists: %s", async (exists) => {
    if (exists) await signUp({ email: EMAIL, password: OLD_PASSWORD });
    renderAt("/reset-password");
    await userEvent.type(screen.getByLabelText("Email"), EMAIL);
    await userEvent.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(`If an account exists, we will email a reset link to ${EMAIL}.`);
  });

  it("resets through the API, removes the URL token, and requires sign-in with the new password", async () => {
    await signUp({ email: EMAIL, password: OLD_PASSWORD });
    await passwordResetApi.requestLink(EMAIL);
    const router = renderAt("/reset-password?token=demo-token");
    expect(router.state.location.search).toBe("");
    await submitPassword();
    expect(await screen.findByRole("heading", { name: "Password updated" })).toBeInTheDocument();
    expect(getSession().status).toBe("anonymous");
    await expect(signIn({ email: EMAIL, password: OLD_PASSWORD, remember: true })).rejects.toMatchObject({ status: 401 });
    await expect(signIn({ email: EMAIL, password: NEW_PASSWORD, remember: true })).resolves.toMatchObject({ email: EMAIL });
    await expect(passwordResetApi.setNewPassword("demo-token", "another789")).rejects.toMatchObject({ status: 422 });
  });

  it("shows invalid-link errors without changing the password", async () => {
    await signUp({ email: EMAIL, password: OLD_PASSWORD });
    renderAt("/reset-password?token=invalid-token");
    await submitPassword();
    expect(await screen.findByRole("alert")).toHaveTextContent("This reset link is invalid or expired.");
    await expect(signIn({ email: EMAIL, password: OLD_PASSWORD, remember: true })).resolves.toMatchObject({ email: EMAIL });
  });

  it("changes the password with current credentials and clears the local session", async () => {
    await signUp({ email: EMAIL, password: OLD_PASSWORD });
    await expect(changePassword("wrong123", NEW_PASSWORD)).rejects.toMatchObject({ status: 401 });
    expect(getSession().status).toBe("authenticated");
    await changePassword(OLD_PASSWORD, NEW_PASSWORD);
    expect(getSession().status).toBe("anonymous");
    await expect(signIn({ email: EMAIL, password: OLD_PASSWORD, remember: true })).rejects.toMatchObject({ status: 401 });
    await expect(signIn({ email: EMAIL, password: NEW_PASSWORD, remember: true })).resolves.toMatchObject({ email: EMAIL });
  });
});
