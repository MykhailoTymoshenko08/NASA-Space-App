import type { Strategy } from "@/shared/api";
import { Badge } from "@/shared/ui/feedback";
import s from "./analysis.module.css";

const money = (value: number, digits = 0) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD",
    minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);

/** Dollar budgets use crop economics; the independent ML income score stays an index. */
export function StrategyBudget({ budget }: { budget: NonNullable<Strategy["budget"]> }) {
  const average = budget.annual_average;
  if (budget.status !== "estimated" || !average || !budget.horizon_total
    || budget.missing_inputs.length > 0 || budget.uses_placeholders) return null;
  const delta = budget.delta_vs_current_per_acre?.base;
  return (
    <section className={s.budget} aria-label="Rough rotation budget">
      <div className={s.tags}>
        <strong>Rough budget</strong>
        <Badge tone="warning">Illustrative</Badge>
      </div>
      <div className={s.budgetNumbers}>
        {(["low", "base", "high"] as const).map((key) => (
          <div key={key}>
            <div className={s.small}>{key === "base" ? "Recent prices" : `${key === "low" ? "Lower" : "Higher"} prices`}</div>
            <strong>{money(average[key].profit_per_acre)}</strong>
            <div className={s.small}>after costs / acre / year</div>
          </div>
        ))}
      </div>
      <p className={s.small}>
        Revenue {money(average.base.revenue_per_acre, 2)} less modeled costs {money(average.base.cost_per_acre, 2)} / acre / year.
        {average.base.field_profit != null && ` About ${money(average.base.field_profit)} / year across ${budget.area_acres} estimated acres.`}
      </p>
      {average.base.return_before_land_per_acre != null && (
        <p className={s.small}>
          Before land cost: {money(average.base.return_before_land_per_acre, 2)} / acre / year.
          {` Land charge: ${money(average.base.return_before_land_per_acre - average.base.profit_per_acre, 2)} / acre / year.`}
        </p>
      )}
      {delta != null && (
        <p className={s.small}>
          {delta > 0 ? "+" : ""}{money(delta)} / acre / year versus your current rotation at base prices.
        </p>
      )}
      <p className={s.small}>
        Returns include production, land, labor and machinery ownership allowances. This is not cash flow.
        Negative values can occur even when cash income is positive. Historical price scenarios are not a profit forecast.
      </p>
      <details>
        <summary>Yearly figures, assumptions and sources</summary>
        <div className={s.budgetTable}>
          <table>
            <thead><tr><th>Year</th><th>Crops</th><th>Reference yield / acre</th><th>Cost / acre</th><th>Return / acre</th><th>Break-even price</th></tr></thead>
            <tbody>
              {budget.years.map((year) => (
                <tr key={year.year}>
                  <td>{year.year}</td>
                  <td>
                    {[...year.main_crops, ...year.cover_crops].map((c) => c.replaceAll("_", " ")).join(" + ")}
                    {year.cost_profile && <div className={s.small}>{year.cost_profile}</div>}
                  </td>
                  <td>{year.yield_per_acre != null ? `${year.yield_per_acre} ${year.yield_unit ?? ""}` : "Not estimated"}</td>
                  <td>{year.scenarios ? money(year.scenarios.base.cost_per_acre) : "Unavailable"}</td>
                  <td>{year.scenarios ? money(year.scenarios.base.profit_per_acre) : "Unavailable"}</td>
                  <td>{year.break_even_price_per_unit != null ? `${money(year.break_even_price_per_unit, 2)} / ${year.yield_unit ?? "unit"}` : "Unavailable"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {budget.horizon_total && (
          <p className={s.small}>
            Base total over {budget.horizon_years} {budget.horizon_years === 1 ? "year" : "years"}: {money(budget.horizon_total.base.profit_per_acre)} / acre.
            {budget.horizon_total.base.field_profit != null && ` About ${money(budget.horizon_total.base.field_profit)} for the estimated field.`}
          </p>
        )}
        <ul className={s.bullets}>{budget.assumptions.map((text, i) => <li key={i}>{text}</li>)}</ul>
        {budget.sources.length > 0 && (
          <ul className={s.bullets} aria-label="Budget sources">
            {budget.sources.map((source, i) => (
              <li key={i}>
                {source.url ? <a href={source.url}>{source.dataset}</a> : source.dataset} ({source.provider})
              </li>
            ))}
          </ul>
        )}
      </details>
    </section>
  );
}
