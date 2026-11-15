# Profitability audit — 2026-11-15

The subtraction was correct, but several input combinations were not a reliable farm budget.
All examples below are enterprise illustrations, not calibrated field forecasts.

## Confirmed defects and corrections

1. Illinois high-productivity production costs were paired with lower statewide historical yields.
   Nebraska dryland costs were paired with state yields including other production systems. Default
   yields now come from the exact published cost profile. The original NASS state-yield series remains
   intact and is used when the farmer supplies a total cost instead of an extension cost profile.
2. Corn after soybeans used a continuous-corn budget minus a uniform nitrogen credit. This missed
   other rotation differences in yield, tillage, insecticide and harvest costs. Published after-soybean
   budgets now replace the full cost/yield pair, with no second nitrogen credit. Illinois repeated
   soybeans also use their published profile.
3. A $99.85 Illinois program implementation estimate was automatically treated as an all-in farm cover
   cost across states. This default is removed. Unknown cover costs now make that budget incomplete;
   explicit zero remains valid. The UI requests incremental seed, planting and termination costs beyond
   the normal cash-crop program. A survey direct-cost median is informational, never an automatic input.
4. The UI called full-cost enterprise returns “profit” without distinguishing cash flow. It now explains
   the inclusion of labor and machinery ownership allowances, shows returns before land, and gives
   per-crop break-even prices. Lower/recent/higher historical prices are sensitivity cases, not forecasts.

## Checks against original sources

- Rebuilt price percentiles, recent averages and historical yield means from the original cached USDA
  release ZIP tables: all stored numeric values and histories matched. These series were not changed.
- Checked line items and reference yields against [Iowa State A1-20, 2026](https://www.extension.iastate.edu/agdm/crops/pdf/a1-20_2026.pdf),
  [Illinois farmdoc, May 2026, Table 2](https://farmdoc.illinois.edu/assets/management/crop-budgets/crop_budgets_2026_May.pdf),
  and [Nebraska 2026 enterprise budgets](https://cap.unl.edu/sites/unl.edu.ianr.agecon.center-for-ag-profitability/files/media/file/2026-nebraska-crop-budgets-r_0.pdf).
- Regression checks reproduce Iowa's 211-bushel corn-after-soybeans budget and $911.98 total cost
  including $274 land cost. Illinois reference checks use the table's prices and land charge, explicitly
  excluding its government payments. No payments are fabricated as grain revenue.
- [Iowa's cover-crop spreadsheet](https://www.extension.iastate.edu/AGDm/crops/html/a1-91.html) explicitly
  labels its example numbers as illustrative rather than producer research. These were not substituted
  as defaults. [University of Minnesota's 2025 survey summary](https://finpack.umn.edu/news/new-cover-crops-report-and-climate-smart-ag-resources-2/)
  reports direct expenses, which cannot silently substitute for an individual farm's complete costs.

## Before and after, with identical prices and land assumptions

No cover costs, subsidies or farmer yield overrides are included in these examples. Land charges here
are fixed comparison assumptions, not new claims about market rents.

| Enterprise | Land charge / acre | Old annual return / acre | Corrected annual return / acre |
|---|---:|---:|---:|
| Iowa corn after soybeans | $270 | -$45.71 | $3.54 |
| Illinois soybeans after corn | $280 | -$90.60 | $47.28 |
| Illinois corn after soybeans | $280 | -$206.99 | -$86.34 |
| Nebraska dryland corn after soybeans | $230 | $62.32 | $105.90 |

Losses are not automatically errors. [Farmdoc's 2026 outlook](https://farmdocdaily.illinois.edu/2026/01/revised-illinois-crop-budgets-for-2026.html)
also projects negative returns on rented corn acres. Historical price stress combined with current
production costs can remain negative; the application must identify that basis clearly.

## Remaining limits

Farm yields, local sale prices, actual land costs, irrigation systems, insurance receipts and program
payments can differ materially. Land placeholders and unavailable crop budgets remain labeled.
Unknown inputs are not zero. ML suitability and income scores do not calibrate dollar or yield forecasts.
