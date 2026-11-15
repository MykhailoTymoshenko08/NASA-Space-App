import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { StrategyBudget } from "@/entities/analysis";
import {
  fetchFieldComparison,
  type ComparedField,
  type FieldComparison,
  type SavedFieldComparisonRequest,
} from "@/entities/comparison";
import { GeometrySketch } from "@/entities/field";
import type { SavedField } from "@/entities/saved-field";
import { ApiError, friendlyMessage } from "@/shared/api";
import { fieldPath, ROUTES } from "@/shared/config";
import { formatAcres, formatDateTime } from "@/shared/lib";
import { Button, ButtonLink } from "@/shared/ui/button";
import { ErrorPanel, Message, Note, Skeleton } from "@/shared/ui/feedback";
import { SelectField, TextField } from "@/shared/ui/form";
import { Icon } from "@/shared/ui/icon";
import { cellOf, compareValue, hasValue, usd } from "../lib/compare";
import { isPoint, savedRings, savedSearch } from "../lib/title";
import { CompareTable } from "./CompareTable";
import { FieldLetter } from "./FieldLetter";
import s from "./compare.module.css";

const cx = (...c: (string | false | undefined)[]) => c.filter(Boolean).join(" ");

/**
 * Server-owned comparison of 2 to 4 saved fields (POST /comparisons/saved-fields): asking rents, one crop
 * plan, ranked rows and source limitations. The server picks every winner; this view only presents them.
 */
export function FieldsCompare({ fields, userId }: { fields: readonly SavedField[]; userId: string }) {
  const [rents, setRents] = useState<Record<string, string>>({});
  const [rotation, setRotation] = useState("corn,soybean");
  const [years, setYears] = useState(2);
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
  useEffect(() => {
    if (query.data) previous.current = query.data;
  }, [query.data]);
  const data = query.data ?? previous.current;
  const retryAfter = query.error instanceof ApiError ? query.error.retryAfterSeconds : null;
  useEffect(() => {
    if (!retryAfter) {
      setWaiting(false);
      return;
    }
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
    setValidation(null);
    const next = {
      rent_per_acre,
      plan: { rotation: rotation.split(",") as NonNullable<SavedFieldComparisonRequest["plan"]>["rotation"], horizon_years: years },
    };
    if (JSON.stringify(options) === JSON.stringify(next)) void query.refetch();
    else setOptions(next);
  };
  const missing = query.error instanceof ApiError && query.error.status === 404;
  const unauthorized = query.error instanceof ApiError && query.error.status === 401;
  const updating = query.isFetching && !!data;

  return (
    <div className={s.compare}>
      <form onSubmit={submit} noValidate className={s.settings} aria-label="Comparison settings">
        <div>
          <h2 className={s.h2}>Your numbers</h2>
          <p className={s.muted}>
            Money rows budget one crop plan on every field, at each field's asking rent. Each field starts with the crop
            that follows its last crop.
          </p>
        </div>
        <div className={s.planGrid}>
          <SelectField label="Shared crop rotation" value={rotation} onChange={(e) => setRotation(e.target.value)}>
            <option value="corn,soybean">Corn / soybeans</option>
            <option value="corn">Corn</option>
            <option value="soybean">Soybeans</option>
            <option value="winter_wheat">Winter wheat</option>
          </SelectField>
          <SelectField label="Budget horizon" value={years} onChange={(e) => setYears(Number(e.target.value))}>
            {[1, 2, 3, 4, 5].map((n) => (
              <option value={n} key={n}>
                {n} {n === 1 ? "year" : "years"}
              </option>
            ))}
          </SelectField>
        </div>
        <fieldset className={s.rents}>
          <legend className={s.legend}>Asking rent, $ per acre a year</legend>
          {fields.map((field, i) => {
            const compared = data?.fields.find((f) => f.saved_field_id === field.id);
            const used = compared?.rent;
            return (
              <TextField
                key={field.id}
                label={`${"ABCD"[i]} · ${field.name} asking rent`}
                type="number"
                inputMode="decimal"
                min={0}
                max={5000}
                step="0.01"
                value={rents[field.id] ?? ""}
                placeholder={used?.source === "state_baseline" && used.per_acre != null ? String(used.per_acre) : "State reference"}
                onChange={(e) => setRents((old) => ({ ...old, [field.id]: e.target.value }))}
                hint={rentHint(compared)}
              />
            );
          })}
        </fieldset>
        {validation && (
          <Message tone="error" role="alert">
            {validation}
          </Message>
        )}
        <div className={s.settingsActions}>
          <Button type="submit" variant="primary" disabled={query.isFetching || waiting}>
            {query.isFetching ? "Updating comparison…" : "Update comparison"}
          </Button>
          <span className={s.muted}>Blank rent uses the state reference; $0 means no land charge.</span>
        </div>
      </form>

      {query.isFetching && (
        <div role="status" className={s.muted}>
          {data ? "Updating comparison. Previous results remain below." : "Loading comparison, soil data and budgets…"}
        </div>
      )}
      {query.isError && (
        <ErrorPanel
          title={missing ? "One selected field is no longer available" : "We could not update the comparison"}
          message={missing ? "Return to Saved fields and select the fields again." : friendlyMessage(query.error)}
          actions={
            unauthorized ? (
              <ButtonLink to={`${ROUTES.signIn}?next=${encodeURIComponent(ROUTES.myFields)}`}>Sign in again</ButtonLink>
            ) : (
              !missing && (
                <Button onClick={() => void query.refetch()} disabled={query.isFetching || waiting}>
                  Try again
                </Button>
              )
            )
          }
        />
      )}
      {!data && query.isPending && <CompareSkeleton count={fields.length} />}

      {data && (
        <div className={cx(s.results, updating && s.stale)} aria-busy={updating || undefined}>
          {query.isError && <Message tone="warning">Showing the previous comparison. The latest update failed.</Message>}
          <Verdicts data={data} />
          <FieldCards data={data} saved={fields} />
          <CompareTable data={data} />
          <Note tone="warning" title="Before you decide">
            <ul className={s.warnings}>
              {[...data.warnings, data.disclaimer].filter(Boolean).map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </Note>
        </div>
      )}
    </div>
  );
}

function rentHint(f: ComparedField | undefined): string {
  if (!f) return "USD per acre per year";
  const r = f.rent;
  if (r.source === "farmer" && r.per_acre != null) return `Using your ${usd(r.per_acre, r.per_acre % 1 ? 2 : 0)} per acre.`;
  if (r.is_placeholder || r.per_acre == null) return "State reference unavailable. Enter asking rent ($/acre/year).";
  return `Blank uses the ${f.state} reference, ${usd(r.per_acre)}.`;
}

/* ---------- quick answers ---------- */

const VERDICTS = [
  { key: "net_return", row: "net_return_per_acre", title: "Best return after rent", icon: "check" },
  { key: "soil_productivity", row: "soil_productivity_nccpi", title: "Most productive soil", icon: "layers" },
  { key: "rent_value", row: "rent_per_productivity_point", title: "Most soil for the rent", icon: "pin" },
] as const;

function Verdicts({ data }: { data: FieldComparison }) {
  return (
    <section className={s.verdicts} aria-label="Quick answers">
      {VERDICTS.map((v) => {
        const ids = data.best[v.key];
        const winners = data.fields.filter((f) => ids.includes(f.saved_field_id));
        const row = data.rows.find((r) => r.key === v.row);
        const cell = winners[0] && cellOf(data, v.row, winners[0].saved_field_id);
        const shown = hasValue(cell) && row ? compareValue(cell.value, row.unit) : null;
        return (
          <div key={v.key} className={cx(s.verdict, winners.length > 0 && s.verdictWon)}>
            <span className={s.verdictTitle}>
              <Icon name={v.icon} size={16} />
              {v.title}
            </span>
            {winners.length > 0 ? (
              <>
                <span className={s.verdictWho}>
                  {winners.map((w) => (
                    <FieldLetter key={w.label} label={w.label} size="sm" />
                  ))}
                  <span>
                    {winners.map((w, i) => (
                      <span key={w.label}>
                        {i > 0 && " and "}
                        <span className="visually-hidden">Field {w.label}:</span>{" "}
                        {w.name}
                      </span>
                    ))}
                  </span>
                </span>
                {shown && (
                  <span className={s.verdictValue}>
                    {shown.value} <span className={s.unit}>{shown.unit}</span>
                  </span>
                )}
              </>
            ) : (
              <>
                <span className={s.verdictNone}>No clear winner</span>
                <span className={s.unit}>The values tie, or some fields have no data for this.</span>
              </>
            )}
          </div>
        );
      })}
    </section>
  );
}

/* ---------- one card per field ---------- */

function FieldCards({ data, saved }: { data: FieldComparison; saved: readonly SavedField[] }) {
  return (
    <ul className={s.cards} aria-label="Fields compared">
      {data.fields.map((f) => {
        const own = saved.find((x) => x.id === f.saved_field_id);
        const net = f.net_return_per_acre;
        const place = f.county ? `${f.county.name} County, ${f.county.state_postal}` : f.state;
        const size = f.area_ha != null ? `About ${formatAcres(f.area_ha)} acres` : "Point, no mapped field";
        return (
          <li key={f.saved_field_id} className={s.card}>
            <div className={s.cardHead}>
              <FieldLetter label={f.label} />
              <div className={s.cardTitleBox}>
                <h3 className={s.cardTitle}>
                  <span className="visually-hidden">Field {f.label}:</span>{" "}
                  {f.name}
                </h3>
                <span className={s.muted}>
                  {place} · {size}
                </span>
              </div>
            </div>

            {own && (
              <div className={s.cardSketch}>
                <GeometrySketch
                  rings={savedRings(own)}
                  anchor={own.centroid}
                  dashed={isPoint(own)}
                  label={`Outline of ${f.name}`}
                  width={240}
                  height={96}
                />
              </div>
            )}

            <div className={s.money}>
              <span className={s.moneyLabel}>Return after rent</span>
              {net ? (
                <>
                  <span className={cx(s.moneyValue, net.base < 0 && s.loss)}>
                    {usd(net.base)} <span className={s.unit}>per acre a year{net.base < 0 && " (loss at base prices)"}</span>
                  </span>
                  <span className={s.small}>
                    {usd(net.low)} at lower prices, {usd(net.high)} at higher prices
                  </span>
                </>
              ) : (
                <span className={s.na}>Not available</span>
              )}
              <span className={s.small}>
                Break-even rent:{" "}
                {f.break_even_rent_per_acre ? `${usd(f.break_even_rent_per_acre.base)} per acre` : "Not available"}
              </span>
            </div>

            {(f.strengths.length > 0 || f.cautions.length > 0) && (
              <div className={s.points}>
                {f.strengths.length > 0 && (
                  <ul className={s.pointList} aria-label={`Strengths of field ${f.label}`}>
                    {f.strengths.map((t) => (
                      <li key={t} className={s.strength}>
                        <Icon name="check" size={16} />
                        <span>{t}</span>
                      </li>
                    ))}
                  </ul>
                )}
                {f.cautions.length > 0 && (
                  <ul className={s.pointList} aria-label={`Things to check on field ${f.label}`}>
                    {f.cautions.map((t) => (
                      <li key={t} className={s.caution}>
                        <Icon name="warning" size={16} />
                        <span>{t}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {f.budget?.status === "estimated" && !f.budget.uses_placeholders && f.budget.missing_inputs.length === 0 && (
              <details className={s.budget}>
                <summary>How is this calculated?</summary>
                <StrategyBudget budget={f.budget} />
              </details>
            )}
            {f.data_as_of && <span className={s.small}>Soil data from {formatDateTime(f.data_as_of)}</span>}

            {own && (
              <Link to={fieldPath(savedSearch(own))} className={s.open}>
                Open field {f.label}
                <Icon name="arrow-right" size={16} />
              </Link>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/* ---------- first load ---------- */

function CompareSkeleton({ count }: { count: number }) {
  return (
    <div className={s.results} aria-hidden="true">
      <div className={s.verdicts}>
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} height={104} />
        ))}
      </div>
      <div className={s.cards}>
        {Array.from({ length: count }, (_, i) => (
          <Skeleton key={i} height={320} />
        ))}
      </div>
      <Skeleton height={420} />
    </div>
  );
}
