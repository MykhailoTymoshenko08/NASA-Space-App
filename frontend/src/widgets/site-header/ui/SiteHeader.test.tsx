import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderRoutes } from "@/shared/lib/test";
import { SiteHeader } from "./SiteHeader";

const renderAt = (url: string) =>
  renderRoutes(
    [
      { path: "/", element: <SiteHeader /> },
      { path: "/pick-field", element: <SiteHeader /> },
      { path: "/sign-in", element: <SiteHeader /> },
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

describe("SiteHeader links (desktop design)", () => {
  const main = () => screen.getByRole("navigation", { name: "Main" });

  it("on the landing page links to How it works, with no page marked current", () => {
    renderAt("/");
    expect(within(main()).getByRole("link", { name: "How it works" })).toHaveAttribute("href", "/#how");
    expect(within(main()).queryByRole("link", { name: "Explore the map" })).not.toBeInTheDocument();
    expect(within(main()).queryByRole("link", { current: "page" })).not.toBeInTheDocument();
  });

  it("on other pages links back to the map and marks the current page", () => {
    renderAt("/pick-field");
    expect(within(main()).getByRole("link", { name: "Explore the map" })).toHaveAttribute("href", "/");
    expect(within(main()).getByRole("link", { name: "Pick a field" })).toHaveAttribute("aria-current", "page");
    expect(within(main()).getByRole("link", { name: "Sign in" })).toBeInTheDocument();
  });

  it("on the sign-in page shows only the map links", () => {
    renderAt("/sign-in");
    expect(within(main()).getByRole("link", { name: "Explore the map" })).toBeInTheDocument();
    expect(within(main()).getByRole("link", { name: "Pick a field" })).toBeInTheDocument();
    expect(within(main()).queryByRole("link", { name: "Sign in" })).not.toBeInTheDocument();
  });
});
