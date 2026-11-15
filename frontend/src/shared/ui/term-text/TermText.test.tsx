import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TermsProvider, TermText, type TermEntry } from "./TermText";

const TERMS: TermEntry[] = [
  { id: "gl-et", term: "ET (evapotranspiration)", def: "Water the field gives back.", why: "Its water spending.", match: ["evapotranspiration", "ET"] },
  {
    id: "gl-anomaly",
    term: "Soil moisture anomaly",
    def: "Gap from normal.",
    why: "Wetter or drier than usual.",
    match: ["soil moisture anomaly", "anomaly"],
  },
  { id: "gl-ph", term: "Soil pH", def: "Acid or alkaline.", why: "Nutrient uptake.", match: ["soil pH", "pH"] },
  { id: "gl-vol", term: "m³/m³", def: "Share of water.", why: "The unit.", match: ["m³/m³"] },
];

function renderText(text: string) {
  return render(
    <TermsProvider terms={TERMS}>
      <p>
        <TermText>{text}</TermText>
      </p>
    </TermsProvider>,
  );
}

const termButtons = () => screen.queryAllByRole("button").map((b) => b.textContent);

describe("TermText", () => {
  it("is plain text without a provider", () => {
    render(<TermText>ET is high.</TermText>);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("ET is high.")).toBeInTheDocument();
  });

  it("marks whole terms only, longest phrase first, and keeps the text", () => {
    const { container } = renderText("The Soil moisture anomaly is -1.2 and ET is 3 in, reading 0.27 m³/m³ in the metadata.");
    expect(termButtons()).toEqual(["Soil moisture anomaly", "ET", "m³/m³"]);
    expect(container).toHaveTextContent("The Soil moisture anomaly is -1.2 and ET is 3 in, reading 0.27 m³/m³ in the metadata.");
  });

  it("keeps capitals inside a phrase exact but frees the first letter", () => {
    renderText("Soil pH is 6.4. Et cetera, et al, PH and ph are not terms.");
    expect(termButtons()).toEqual(["Soil pH"]);
  });

  it("opens a popover on hover with what it is, why it matters and a link to the glossary entry", async () => {
    const user = userEvent.setup();
    renderText("ET was high.");
    const term = screen.getByRole("button", { name: "ET" });
    await user.hover(term);
    const pop = screen.getByRole("note", { name: "ET (evapotranspiration)" });
    expect(term).toHaveAttribute("aria-expanded", "true");
    expect(pop).toHaveTextContent("Water the field gives back.");
    expect(pop).toHaveTextContent("Why it matters. Its water spending.");
    expect(screen.getByRole("link", { name: "Learn more in the glossary" })).toHaveAttribute("href", "#gl-et");
  });

  it("opens on keyboard focus and closes with Escape", async () => {
    const user = userEvent.setup();
    renderText("ET was high.");
    await user.tab();
    expect(screen.getByRole("note")).toBeInTheDocument();
    await user.tab();
    expect(screen.getByRole("link", { name: "Learn more in the glossary" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ET" })).toHaveFocus();
  });
});
