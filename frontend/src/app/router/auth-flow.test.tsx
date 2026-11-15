import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { getSession, signOut } from "@/entities/session";
import { SignInPage } from "@/pages/sign-in";
import { renderRoutes } from "@/shared/lib/test";
import { handlers } from "@/shared/mocks";
import { SignUpPage } from "@/pages/sign-up";

const server = setupServer(...handlers);
beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const routes = [
  { path: "/sign-up", element: <SignUpPage /> },
  { path: "/sign-in", element: <SignInPage /> },
  { path: "/my-fields", element: <p>My fields page</p> },
];

describe("accounts", () => {
  beforeEach(() => localStorage.clear());

  it("checks the password rules before sending", async () => {
    renderRoutes(routes, "/sign-up");
    await userEvent.type(screen.getByLabelText("Email"), "name@");
    await userEvent.type(screen.getByLabelText("Password"), "short");
    expect(screen.getByText("Needed: at least 8 characters")).toBeInTheDocument();
    expect(screen.getByText("Needed: at least one number")).toBeInTheDocument();
    expect(screen.getByText("Done: at least one letter")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Create account/ }));
    expect(screen.getByText("Enter an email like name@example.com.")).toBeInTheDocument();
    expect(screen.getByText("Your password does not meet the rules below.")).toBeInTheDocument();
    expect(screen.getByText("Agree to the terms to continue.")).toBeInTheDocument();
  });

  it("creates an account, then refuses the same email again", async () => {
    renderRoutes(routes, "/sign-up");
    await userEvent.type(screen.getByLabelText("Email"), "farmer@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "corn2026");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: /Create account/ }));
    expect(await screen.findByText("Account created. You are signed in as farmer@example.com.")).toBeInTheDocument();
    expect(getSession().status).toBe("authenticated");
    await signOut();
    expect(getSession().status).toBe("anonymous");
  });

  it("signs in and returns to the page that asked", async () => {
    renderRoutes(routes, "/sign-up");
    await userEvent.type(screen.getByLabelText("Email"), "back@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "soybean1");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: /Create account/ }));
    await screen.findByText(/Account created/);
    await signOut();

    const router = renderRoutes(routes, "/sign-in?next=%2Fmy-fields");
    await userEvent.type(screen.getAllByLabelText("Email").at(-1)!, "back@example.com");
    await userEvent.type(screen.getAllByLabelText("Password").at(-1)!, "wrong-pass1");
    await userEvent.click(screen.getByRole("button", { name: /^Sign in/ }));
    expect(await screen.findByText(/do not match an account/)).toBeInTheDocument();

    const pw = screen.getAllByLabelText("Password").at(-1)!;
    await userEvent.clear(pw);
    await userEvent.type(pw, "soybean1");
    await userEvent.click(screen.getByRole("button", { name: /^Sign in/ }));
    await screen.findByText("My fields page");
    expect(router.state.location.pathname).toBe("/my-fields");
  });

  it("keeps the protected destination while switching to signup", async () => {
    const router = renderRoutes(routes, "/sign-in?next=%2Fmy-fields");
    await userEvent.click(screen.getByRole("link", { name: "Create an account" }));
    expect(router.state.location.search).toBe("?next=%2Fmy-fields");
    await userEvent.type(screen.getByLabelText("Email"), "new-return@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "password123");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: /Create account/ }));
    await screen.findByText("My fields page");
    expect(router.state.location.pathname).toBe("/my-fields");
    await signOut();
  });

  it("keeps the protected destination while switching back to sign-in", async () => {
    const router = renderRoutes(routes, "/sign-up?next=%2Fmy-fields");
    await userEvent.click(screen.getByRole("link", { name: "Sign in" }));
    expect(router.state.location.pathname).toBe("/sign-in");
    expect(router.state.location.search).toBe("?next=%2Fmy-fields");
  });
});
