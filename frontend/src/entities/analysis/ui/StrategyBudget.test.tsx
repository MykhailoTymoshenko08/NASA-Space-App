import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Strategy } from "@/shared/api";
import { StrategyBudget } from "./StrategyBudget";
import { StrategyCard } from "./StrategyCard";

type Budget = NonNullable<Strategy["budget"]>;
const scenarios = {
  low: { revenue_per_acre: 600, cost_per_acre: 850, profit_per_acre: -250, field_profit: -25000 },
  base: { revenue_per_acre: 800, cost_per_acre: 850, profit_per_acre: -50, field_profit: -5000 },
  high: { revenue_per_acre: 1100, cost_per_acre: 850, profit_per_acre: 250, field_profit: 25000 },
};
const budget: Budget = {
  status: "estimated", currency: "USD", horizon_years: 1, area_acres: 100,
  years: [{ year: 1, main_crops: ["corn"], cover_crops: ["cereal_rye"], production_cost_per_acre: 600,
    land_rent_per_acre: 200, cover_cost_per_acre: 50, nitrogen_credit_per_acre: 0,
    yield_per_acre: 200, yield_unit: "bu", scenarios }],
  annual_average: scenarios, horizon_total: scenarios,
  delta_vs_current_per_acre: { low: -50, base: -50, high: -50 },
  is_illustrative: true, uses_placeholders: false, baseline_version: "test",
  assumptions: ["State yields are not field predictions."], missing_inputs: [],
  sources: [{ dataset: "Extension budget", provider: "University", url: "https://example.org/budget" }],
};

describe("rotation budget", () => {
  it("labels losses, annual units, field scaling and comparison clearly", async () => {
    render(<StrategyBudget budget={budget} />);
    expect(screen.getByText("Illustrative")).toBeInTheDocument();
    expect(screen.getByText("-$250")).toBeInTheDocument();
    expect(screen.getByText("-$50", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText(/profit forecast/)).toBeInTheDocument();
    expect(screen.getByText(/100 estimated acres/)).toHaveTextContent("-$5,000 / year");
    expect(screen.getByText(/versus your current rotation/)).toHaveTextContent("-$50 / acre / year");
    await userEvent.click(screen.getByText("Yearly figures, assumptions and sources"));
    expect(screen.getByRole("link", { name: "Extension budget" })).toHaveAttribute("href", "https://example.org/budget");
    expect(screen.getByText("State yields are not field predictions.")).toBeVisible();
  });

  it.each<[string, Partial<Budget>]>([
    ["partial", { status: "partial", annual_average: null, horizon_total: null,
      missing_inputs: ["No local barley budget."] }],
    ["unavailable", { status: "unavailable", annual_average: null, horizon_total: null }],
    ["missing annual figures", { annual_average: null }],
    ["missing horizon totals", { horizon_total: null }],
    ["missing inputs", { missing_inputs: ["Unknown cover cost."] }],
    ["placeholder inputs", { uses_placeholders: true }],
  ])("hides the entire profitability block for %s while keeping the rotation", (_, patch) => {
    const strategy: Strategy = {
      id: "corn-soy", name: "Corn and soybean rotation", is_current: false,
      rotation: [{ season_index: 0, crop: "Corn", role: "cash_crop" }], score: 65,
      score_breakdown: [], confidence: "medium", summary: "Adds crop diversity.",
      benefits: [], risks: [], evidence: [], information_gaps: [], needs_local_review: true,
      budget: { ...budget, ...patch },
    };
    render(<StrategyCard strategy={strategy} index={0} baselineScore={60} open={false} onToggle={() => {}} />);
    expect(screen.getByRole("heading", { name: strategy.name })).toBeInTheDocument();
    expect(screen.getByText(strategy.summary)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Rough rotation budget" })).not.toBeInTheDocument();
    expect(screen.queryByText("Rough budget")).not.toBeInTheDocument();
    expect(screen.queryByText(/unavailable|Unknown cover cost|No local barley budget/i)).not.toBeInTheDocument();
  });

  it("shows a complete zero-return estimate", () => {
    const zero = { revenue_per_acre: 850, cost_per_acre: 850, profit_per_acre: 0, field_profit: 0 };
    const totals = { low: zero, base: zero, high: zero };
    render(<StrategyBudget budget={{ ...budget, annual_average: totals, horizon_total: totals }} />);
    expect(screen.getByRole("region", { name: "Rough rotation budget" })).toBeInTheDocument();
    expect(screen.getAllByText("$0", { selector: "strong" })).toHaveLength(3);
  });
});
