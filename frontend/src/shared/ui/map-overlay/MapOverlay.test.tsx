import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { MapLegend, MapStage, MapZoomControls } from "./MapOverlay";

const noop = () => undefined;

describe("MapStage full screen", () => {
  it("toggles from the zoom controls, locks page scroll, and leaves on Escape", async () => {
    const { container } = render(
      <MapStage>
        <MapZoomControls onZoomIn={noop} onZoomOut={noop} />
      </MapStage>,
    );
    const stage = container.firstElementChild as HTMLElement;
    await userEvent.click(screen.getByRole("button", { name: "Show the map full screen" }));
    expect(stage.className).toMatch(/stageFull/);
    expect(document.documentElement.style.overflow).toBe("hidden");

    await userEvent.keyboard("{Escape}");
    expect(stage.className).not.toMatch(/stageFull/);
    expect(document.documentElement.style.overflow).toBe("");
    expect(screen.getByRole("button", { name: "Show the map full screen" })).toBeInTheDocument();
  });
});

describe("MapLegend", () => {
  it("has a toggle that opens and closes it (shown on phones only)", async () => {
    render(<MapLegend title="Counties" items={[{ label: "County", fill: "#fff", line: "#000" }]} />);
    const toggle = screen.getByRole("button", { name: "Legend" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Hide legend" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("County")).toBeInTheDocument();
  });
});
