import { useId } from "react";
import type { components } from "@/shared/api";
import { Button } from "@/shared/ui/button";
import { SelectField, TextField } from "@/shared/ui/form";

export type CropBudgetDraft = {
  crop: string;
  low: string;
  base: string;
  high: string;
  production: string;
};

type CropBudgetInput = components["schemas"]["CropBudgetInput"];
type ParsedCropBudgets =
  | { overrides: CropBudgetInput[]; error: null }
  | { overrides: []; error: string };

const CROPS = [
  { value: "corn", label: "Corn" },
  { value: "soybean", label: "Soybeans" },
  { value: "winter_wheat", label: "Winter wheat" },
  { value: "sorghum", label: "Sorghum" },
  { value: "oats", label: "Oats" },
  { value: "barley", label: "Barley" },
  { value: "alfalfa", label: "Alfalfa" },
  { value: "corn+soybean", label: "Corn + soybeans (double crop)" },
];

/** Validate all supplied figures; a blank value is unknown, while an explicit zero remains zero. */
export function parseCropBudgets(rows: CropBudgetDraft[]): ParsedCropBudgets {
  const overrides: CropBudgetInput[] = [];
  const seen = new Set<string>();
  for (const [index, row] of rows.entries()) {
    const crop = row.crop.trim();
    const option = CROPS.find((item) => item.value === crop);
    if (!option) return { overrides: [], error: `Choose a crop for budget ${index + 1}.` };
    if (seen.has(crop)) return { overrides: [], error: `Provide only one budget for ${option.label.toLowerCase()}.` };
    seen.add(crop);
    const raw = [row.low, row.base, row.high, row.production];
    if (raw.some((value) => value.trim() === "")) {
      return { overrides: [], error: `${option.label}: enter all revenue and production cost figures, or remove this crop budget.` };
    }
    const [low, base, high, production] = raw.map(Number) as [number, number, number, number];
    if ([low, base, high].some((value) => !Number.isFinite(value) || value < 0 || value > 100000)) {
      return { overrides: [], error: `${option.label}: gross revenue must be from $0 to $100,000 per acre per year.` };
    }
    if (!Number.isFinite(production) || production < 0 || production > 10000) {
      return { overrides: [], error: `${option.label}: non-land production cost must be from $0 to $10,000 per acre per year.` };
    }
    if (!(low <= base && base <= high)) {
      return { overrides: [], error: `${option.label}: revenue must follow lower prices ≤ base prices ≤ higher prices.` };
    }
    overrides.push({ crop, revenue_per_acre: { low, base, high }, production_cost_per_acre: production });
  }
  return { overrides, error: null };
}

/** Optional local crop economics, shared by analysis setup and field comparison. */
export function CropBudgetInputs({ rows, onChange }: {
  rows: CropBudgetDraft[];
  onChange: (rows: CropBudgetDraft[]) => void;
}) {
  const titleId = useId();
  const selected = new Set(rows.map((row) => row.crop));
  const next = CROPS.find((crop) => !selected.has(crop.value));
  const update = (index: number, key: keyof CropBudgetDraft, value: string) =>
    onChange(rows.map((row, i) => i === index ? { ...row, [key]: value } : row));

  return (
    <section aria-labelledby={titleId} style={{ display: "grid", gap: "var(--s-12)", minWidth: 0 }}>
      <h3 id={titleId} style={{ margin: 0 }}>Your crop budgets</h3>
      <p style={{ margin: 0 }}>
        Optional: replace reference figures with your own crop revenue and costs. Gross revenue includes grain income before costs.
        Non-land production costs exclude land and cover crops; those charges apply separately.
      </p>
      {rows.map((row, index) => {
        const cropLabel = CROPS.find((crop) => crop.value === row.crop)?.label ?? `Crop ${index + 1}`;
        return (
          <fieldset key={index} style={{ minWidth: 0, margin: 0, padding: "var(--s-12)", border: "1px solid var(--color-line)" }}>
            <legend>Crop budget {index + 1}</legend>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(180px, 100%), 1fr))", gap: "var(--s-12)" }}>
              <SelectField label="Crop" value={row.crop} onChange={(event) => update(index, "crop", event.target.value)}>
                {CROPS.map((crop) => (
                  <option key={crop.value} value={crop.value} disabled={crop.value !== row.crop && selected.has(crop.value)}>{crop.label}</option>
                ))}
              </SelectField>
              <TextField label="Lower-price gross revenue ($/acre/year)" type="number" inputMode="decimal" min={0} max={100000} step="0.01"
                value={row.low} onChange={(event) => update(index, "low", event.target.value)} />
              <TextField label="Base-price gross revenue ($/acre/year)" type="number" inputMode="decimal" min={0} max={100000} step="0.01"
                value={row.base} onChange={(event) => update(index, "base", event.target.value)} />
              <TextField label="Higher-price gross revenue ($/acre/year)" type="number" inputMode="decimal" min={0} max={100000} step="0.01"
                value={row.high} onChange={(event) => update(index, "high", event.target.value)} />
              <TextField label="Non-land production cost ($/acre/year)" type="number" inputMode="decimal" min={0} max={10000} step="0.01"
                value={row.production} onChange={(event) => update(index, "production", event.target.value)} />
            </div>
            <Button variant="ghost" aria-label={`Remove ${cropLabel.toLowerCase()} budget`}
              onClick={() => onChange(rows.filter((_, i) => i !== index))}>Remove</Button>
          </fieldset>
        );
      })}
      <div>
        <Button disabled={!next} onClick={() => {
          if (next) onChange([...rows, { crop: next.value, low: "", base: "", high: "", production: "" }]);
        }}>Add crop budget</Button>
      </div>
    </section>
  );
}
