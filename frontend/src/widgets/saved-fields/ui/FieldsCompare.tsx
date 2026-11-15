import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type CSSProperties, type FormEvent } from "react";
import { Link } from "react-router";
import { StrategyBudget } from "@/entities/analysis";
import { fetchFieldComparison, type ComparisonRow, type FieldComparison, type SavedFieldComparisonRequest } from "@/entities/comparison";
import { QUALITY } from "@/entities/metric";
import type { SavedField } from "@/entities/saved-field";
import { CropBudgetInputs, parseCropBudgets, type CropBudgetDraft } from "@/features/configure-budget";
import { ApiError, friendlyMessage } from "@/shared/api";
import { fieldPath, ROUTES } from "@/shared/config";
import { formatAcres, formatDateTime, toDisplay } from "@/shared/lib";
import { Button, ButtonLink } from "@/shared/ui/button";
import { Badge, ErrorPanel, Message, Skeleton } from "@/shared/ui/feedback";
import { SelectField, TextField } from "@/shared/ui/form";
import { savedSearch } from "../lib/title";
import s from "./saved-fields.module.css";

const GROUPS = { money: "Money · illustrative budget", land: "Land", soil: "Soil", history: "Crop history", climate: "Climate" };
const money = (value: number) => new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2,
}).format(value);

function display(value: string | number, unit: string) {
  if (typeof value === "number" && unit.startsWith("USD")) {
    return `${money(value)}${unit === "USD/year" ? " / year" : unit === "USD/acre/point" ? " / acre / point" : " / acre / year"}${value < 0 ? " (loss)" : ""}`;
  }
  if (typeof value === "number" && unit === "km") return `${(value * 0.621371).toFixed(1)} mi`;
  const result = toDisplay(value, unit);
  return `${result.value}${result.unit ? ` ${result.unit}` : ""}`;
}

function CompareRow({ row, fields }: { row: ComparisonRow; fields: readonly SavedField[] }) {
  return (
    <div role="row" className={`${s.row} ${s.comparisonRow} ${row.same_for_all ? s.sameRow : ""}`}>
      <div role="rowheader" className={s.rowHead}>
        <span className={s.rowLabel}>{row.label}</span>
        {row.target && <span className={s.small}>Best {row.target.min.toFixed(1)} to {row.target.max.toFixed(1)}</span>}
        {row.same_for_all && <span className={s.small}>Same for all fields</span>}
        {row.note && <span className={s.small}>{row.note}</span>}
      </div>
      {fields.map((field, i) => {
        const cell = row.cells.find((item) => item.saved_field_id === field.id);
        const unavailable = !cell || cell.quality === "unavailable" || cell.value === null;
        const best = row.best.includes(field.id);
        return (
          <div role="cell" className={`${s.cell} ${best ? s.bestCell : ""}`} key={field.id}>
            <span className={s.mobileField}>{"ABCD"[i]} · {field.name}</span>
            <span className={unavailable ? s.cellNa : s.cellText}>
              {unavailable ? "Not available" : display(cell.value!, row.unit)}
            </span>
            {best && <Badge tone="success">Best</Badge>}
            {!unavailable && row.group !== "money" && <span className={s.small}>{QUALITY[cell.quality].label}</span>}
            {cell?.note && (unavailable ? <span className={s.small}>{cell.note}</span>
              : <details className={s.cellNote}><summary>Data notes</summary><p>{cell.note}</p></details>)}
          </div>
        );
      })}
    </div>
  );
}

/** Server-owned comparison: asking rents, one crop plan, ranked rows and source limitations. */
export function FieldsCompare({ fields, userId }: { fields: readonly SavedField[]; userId: string }) {
  const [rents, setRents] = useState<Record<string, string>>({});
  const [rotation, setRotation] = useState("corn,soybean");
  const [years, setYears] = useState(2);
  const [cropBudgets, setCropBudgets] = useState<CropBudgetDraft[]>([]);
  const [options, setOptions] = useState<Omit<SavedFieldComparisonRequest, "saved_field_ids">>({});
  const [validation, setValidation] = useState<string | null>(null);
  const [waiting, setWaiting] = useState(false);
  const body: SavedFieldComparisonRequest = { saved_field_ids: fields.map((field) => field.id), ...options };
  const query = useQuery({
    queryKey: ["field-comparison", userId, fields.map((field) => [field.id, field.updated_at]), body],
    queryFn: ({ signal }) => fetchFieldComparison(body, signal),
    placeholderData: keepPreviousData,
    retry: false,
    refetchOnReconnect: false,
  });
  const previous = useRef<FieldComparison | undefined>(undefined);
  useEffect(() => { if (query.data) previous.current = query.data; }, [query.data]);
  const data = query.data ?? previous.current;
  const retryAfter = query.error instanceof ApiError ? query.error.retryAfterSeconds : null;
  useEffect(() => {
    if (!retryAfter) { setWaiting(false); return; }
    setWaiting(true);
    const timer = setTimeout(() => setWaiting(false), retryAfter * 1000);
    return () => clearTimeout(timer);
  }, [query.error, retryAfter]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const rent_per_acre: Record<string, number> = {};
    for (const field of fields) {
      const raw = rents[field.id]?.trim() ?? "";
      if (!raw) continue;
      const value = Number(raw);
      if (!Number.isFinite(value) || value < 0 || value > 5000) {
        setValidation("Enter rents from $0 to $5,000 per acre per year, or leave blank for the state reference.");
        return;
      }
      rent_per_acre[field.id] = value;
    }
    const crop = parseCropBudgets(cropBudgets);
    if (crop.error) {
      setValidation(crop.error);
      return;
    }
    setValidation(null);
    const next = { rent_per_acre, plan: {
      rotation: rotation.split(",") as NonNullable<SavedFieldComparisonRequest["plan"]>["rotation"], horizon_years: years,
    }, ...(crop.overrides.length > 0 ? { crop_overrides: crop.overrides } : {}) };
    if (JSON.stringify(options) === JSON.stringify(next)) void query.refetch();
    else setOptions(next);
  };
  const missing = query.error instanceof ApiError && query.error.status === 404;
  const unauthorized = query.error instanceof ApiError && query.error.status === 401;

  return (
    <div className={s.comparison}>
      <form onSubmit={submit} noValidate className={s.comparisonForm} aria-label="Comparison settings">
        <div className={s.settingsGrid}>
          <SelectField label="Shared crop rotation" value={rotation} onChange={(e) => setRotation(e.target.value)}>
            <option value="corn,soybean">Corn / soybeans</option>
            <option value="corn">Corn</option>
            <option value="soybean">Soybeans</option>
            <option value="winter_wheat">Winter wheat</option>
          </SelectField>
          <SelectField label="Budget horizon" value={years} onChange={(e) => setYears(Number(e.target.value))}>
            {[1, 2, 3, 4, 5].map((n) => <option value={n} key={n}>{n} {n === 1 ? "year" : "years"}</option>)}
          </SelectField>
        </div>
        <p className={s.small}>Each field starts with the crop that follows its last crop. Blank rent uses the state reference; $0 means no land charge.</p>
        <div className={s.rentGrid}>
          {fields.map((field, i) => {
            const used = data?.fields.find((f) => f.saved_field_id === field.id)?.rent;
            return <TextField key={field.id} label={`${"ABCD"[i]} · ${field.name} asking rent`}
              type="number" inputMode="decimal" min={0} max={5000} step="0.01"
              value={rents[field.id] ?? ""} placeholder={used?.source === "state_baseline" && used.per_acre != null ? String(used.per_acre) : "State reference"}
              onChange={(e) => setRents((old) => ({ ...old, [field.id]: e.target.value }))}
              hint={used?.is_placeholder ? "State reference unavailable. Enter asking rent ($/acre/year)." : "USD per acre per year"} />;
          })}
        </div>
        <CropBudgetInputs rows={cropBudgets} onChange={setCropBudgets} />
        {validation && <Message tone="error" role="alert">{validation}</Message>}
        <Button type="submit" variant="primary" disabled={query.isFetching || waiting}>
          {query.isFetching ? "Updating comparison…" : "Update comparison"}
        </Button>
      </form>
      {query.isFetching && <div role="status">{data ? "Updating comparison. Previous results remain below." : "Loading comparison, soil data and budgets…"}</div>}
      {query.isPending && <Skeleton height={240} />}
      {query.isError && <ErrorPanel title={missing ? "One selected field is no longer available" : "We could not update the comparison"}
        message={missing ? "Return to Saved fields and select the fields again." : friendlyMessage(query.error)}
        actions={unauthorized
          ? <ButtonLink to={`${ROUTES.signIn}?next=${encodeURIComponent(ROUTES.myFields)}`}>Sign in again</ButtonLink>
          : !missing && <Button onClick={() => void query.refetch()} disabled={query.isFetching || waiting}>Try again</Button>} />}
      {data && <>
        {query.isError && <Message tone="warning">Showing the previous comparison. The latest update failed.</Message>}
        <div className={s.small}>Comparison from {formatDateTime(data.generated_at)}. Values shown in US units.</div>
        {data.warnings.map((warning) => <Message tone="warning" key={warning}>{warning}</Message>)}
        <div className={s.summaryGrid}>
          {data.fields.map((field) => <section className={s.summaryCard} key={field.saved_field_id} aria-label={`${field.label} · ${field.name} summary`}>
            <h2 className={s.colTitle}>{field.label} · {field.name}</h2>
            <p className={s.small}>{field.county ? `${field.county.name}, ${field.state}` : field.state} · {field.area_ha == null ? "Point, no mapped field" : `About ${formatAcres(field.area_ha)} acres`}</p>
            <div className={s.small}>Return after rent · per acre / year</div>
            <strong className={s.cellBig}>{field.net_return_per_acre ? money(field.net_return_per_acre.base) : "Not available"}</strong>
            {field.net_return_per_acre && field.net_return_per_acre.base < 0 && <span>Loss at base prices</span>}
            <p className={s.small}>Break-even rent: {field.break_even_rent_per_acre ? `${money(field.break_even_rent_per_acre.base)} / acre` : "Not available"}</p>
            {field.strengths.length > 0 && <ul className={s.comparisonBullets}>{field.strengths.map((text) => <li key={text}>{text}</li>)}</ul>}
            {field.cautions.length > 0 && <details><summary>Things to check ({field.cautions.length})</summary><ul className={s.comparisonBullets}>{field.cautions.map((text) => <li key={text}>{text}</li>)}</ul></details>}
            {field.data_as_of && <p className={s.small}>Soil data from {formatDateTime(field.data_as_of)}</p>}
            {field.budget?.status === "estimated" && !field.budget.uses_placeholders && field.budget.missing_inputs.length === 0 &&
              <details><summary>How is this calculated?</summary><StrategyBudget budget={field.budget} /></details>}
            <Link to={fieldPath(savedSearch(fields.find((saved) => saved.id === field.saved_field_id)!))}>Open field {field.label}</Link>
          </section>)}
        </div>
        <div className={s.tableWrap}>
          <div role="table" aria-label="Comparison of selected fields" className={`${s.table} ${s.comparisonTable}`} style={{ "--compare-columns": fields.length } as CSSProperties}>
            <div role="row" className={`${s.row} ${s.headRow} ${s.comparisonRow}`}>
              <div role="columnheader" className={s.colHeadLabel}>Measure</div>
              {fields.map((field, i) => <div role="columnheader" className={s.colHead} key={field.id}>
                <span className={s.colTitle}>{"ABCD"[i]} · {field.name}</span>
                <Link to={fieldPath(savedSearch(field))}>Open field</Link>
              </div>)}
            </div>
            {(Object.keys(GROUPS) as (keyof typeof GROUPS)[]).map((group) => <div role="rowgroup" key={group}>
              <div role="row" className={s.groupRow}><div role="cell" aria-colspan={fields.length + 1}>{GROUPS[group]}</div></div>
              {data.rows.filter((row) => row.group === group).map((row) => <CompareRow row={row} fields={fields} key={row.key} />)}
            </div>)}
          </div>
        </div>
        <p className={s.small}>{data.disclaimer}</p>
      </>}
    </div>
  );
}
