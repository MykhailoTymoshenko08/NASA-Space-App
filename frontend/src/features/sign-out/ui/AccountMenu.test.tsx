import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { signOut } from "@/entities/session";
import { ApiError } from "@/shared/api";
import { renderRoutes } from "@/shared/lib/test";
import { AccountMenu } from "./AccountMenu";

vi.mock("@/entities/session", () => ({ signOut: vi.fn() }));

it("shows a failed logout and lets the user retry before leaving", async () => {
  vi.mocked(signOut).mockRejectedValueOnce(new ApiError({
    code: "NETWORK", message: "We couldn't reach our server. Check your connection and try again.",
  })).mockResolvedValueOnce(undefined);
  const router = renderRoutes([
    { path: "/my-fields", element: <AccountMenu email="farmer@example.com" /> },
    { path: "/", element: <p>Home</p> },
  ], "/my-fields");
  await userEvent.click(screen.getByRole("button", { name: "Account" }));
  await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("We couldn't reach our server.");
  expect(router.state.location.pathname).toBe("/my-fields");
  await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(await screen.findByText("Home")).toBeInTheDocument();
});
