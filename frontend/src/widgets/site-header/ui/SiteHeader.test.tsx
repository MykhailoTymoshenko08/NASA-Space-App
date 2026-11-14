import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderRoutes } from "@/shared/lib/test";
import { SiteHeader } from "./SiteHeader";

const renderAt = (url: string) =>
  renderRoutes(
    [
      { path: "/", element: <SiteHeader /> },
      { path: "/pick-field", element: <SiteHeader /> },
    ],
    url,
  );

describe("SiteHeader burger menu", () => {
  it("opens the menu under the header and closes it after navigating", async () => {
    const router = renderAt("/");
    const burger = screen.getByRole("button", { name: "Menu" });
    expect(burger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("navigation", { name: "Menu" })).not.toBeInTheDocument();

    await userEvent.click(burger);
    expect(burger).toHaveAttribute("aria-expanded", "true");
    const menu = screen.getByRole("navigation", { name: "Menu" });
    expect(burger).toHaveAttribute("aria-controls", menu.id);
    expect(within(menu).getByRole("link", { name: "Sign in" })).toBeInTheDocument();

    await userEvent.click(within(menu).getByRole("link", { name: "Pick a field" }));
    expect(router.state.location.pathname).toBe("/pick-field");
    expect(screen.queryByRole("navigation", { name: "Menu" })).not.toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    renderAt("/");
    await userEvent.click(screen.getByRole("button", { name: "Menu" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("navigation", { name: "Menu" })).not.toBeInTheDocument();
  });
});
