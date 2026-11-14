import { useQueries } from "@tanstack/react-query";
import { Link } from "react-router";
import { countyLine, fetchSnapshot, snapshotQueryKey } from "@/entities/field";
import { QUALITY } from "@/entities/metric";
import type { SavedField } from "@/entities/saved-field";
import { friendlyMessage, type Metric } from "@/shared/api";
import { fieldPath } from "@/shared/config";
import { formatAcres, toDisplayNumber } from "@/shared/lib";
import { Skeleton } from "@/shared/ui/feedback";
import { MeterBar } from "@/shared/ui/progress";
import { savedCrop, savedRef, savedSearch, shortId } from "../lib/title";
import s from "./saved-fields.module.css";

/** Rows of the comparison: metric keys from the contract, with a bar color per measure. */
const METRIC_ROWS: { key: string; label: string; color: string; decimals: number }[] = [
  { key: "soil_wetness_surface", label: "Surface soil wetness (0–1)", color: "var(--color-data-soil)", decimals: 2 },
  { key: "soil_organic_matter_pct", label: "Soil organic matter", color: "var(--color-data-soil-chem)", decimals: 1 },
  { key: "soil_ph", label: "Soil pH", color: "var(--color-data-soil-chem)", decimals: 1 },
  { key: "precip_30d_total", label: "Rain, last 30 days", color: "var(--color-data-rain)", decimals: 1 },
  { key: "air_temp_mean_2m", label: "Air temperature", color: "var(--color-data-temp)", decimals: 0 },
  { key: "soil_nitrogen_total", label: "Soil nitrogen (total)", color: "var(--color-data-nitrogen)", decimals: 1 },
];

const formatAcresOf = (f: SavedField) => (f.area_ha != null ? formatAcres(f.area_ha) : "Not available");

const fmt = (v: number, d: number) => v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

/**
 * Side-by-side base conditions. No compare endpoint exists, so this reuses POST /snapshots per field
 * (by CSB id, else by the saved centroid). Values are converted to US units; each row says how it was obtained.
 */
export function FieldsCompare({ fields }: { fields: readonly SavedField[] }) {
  const snaps = useQueries({
    queries: fields.map((f) => ({
      queryKey: snapshotQueryKey(savedRef(f)),
      queryFn: ({ signal }: { signal: AbortSignal }) => fetchSnapshot(savedRef(f), signal),
    })),
  });
  const cols = fields.length;
  const grid = { gridTemplateColumns: `220px repeat(${cols}, minmax(0, 1fr))` };

  const metricOf = (i: number, key: string): Metric | undefined => snaps[i]?.data?.metrics.find((m) => m.key === key);

  const textRow = (label: string, unit: string, cell: (f: SavedField, i: number) => string) => (
    <div role="row" className={s.row} style={grid} key={label}>
      <div role="rowheader" className={s.rowHead}>
        <span className={s.rowLabel}>{label}</span>
        <span className={s.small}>{unit}</span>
      </div>
      {fields.map((f, i) => (
        <div role="cell" className={s.cell} key={f.id}>
          <span className={s.cellText}>{cell(f, i)}</span>
        </div>
      ))}
    </div>
  );

  return (
    <div className={s.tableWrap}>
      <div role="table" aria-label="Comparison of selected fields" className={s.table}>
        <div role="row" className={`${s.row} ${s.headRow}`} style={grid}>
          <div role="columnheader" className={s.colHeadLabel}>
            Measure
          </div>
          {fields.map((f) => (
            <div role="columnheader" className={s.colHead} key={f.id}>
              <span className={s.colTitle}>{f.name}</span>
              <span className={s.id}>{shortId(f)}</span>
              <Link to={fieldPath(savedSearch(f))} className={s.small}>
                Open field
              </Link>
            </div>
          ))}
        </div>

        {textRow("Location", "County and state", (f, i) => {
          const sel = snaps[i]?.data?.selection;
          return sel ? countyLine(sel) : f.state;
        })}
        {textRow("Latest crop", "Your record or USDA crop maps", (f, i) =>
          savedCrop(f) ?? snaps[i]?.data?.selection.crop_class ?? "None recorded",
        )}
        {textRow("Area", "Acres, about", (f) => formatAcresOf(f))}

        {METRIC_ROWS.map((row) => {
          const values = fields.map((_, i) => {
            const m = metricOf(i, row.key);
            return m && m.quality !== "unavailable" && typeof m.value === "number" ? toDisplayNumber(m.value, m.unit) : null;
          });
          const max = Math.max(0.0001, ...values.map((v) => (v ? Math.abs(v.value) : 0)));
          const sample = fields.map((_, i) => metricOf(i, row.key)).find((m) => m && m.quality !== "unavailable");
          const unit = values.find((v) => v)?.unit ?? "";
          const unitLine = [unit || null, sample ? QUALITY[sample.quality].label : null].filter(Boolean).join(". ");
          return (
            <div role="row" className={s.row} style={grid} key={row.key}>
              <div role="rowheader" className={s.rowHead}>
                <span className={s.rowLabel}>{row.label}</span>
                <span className={s.small}>{unitLine || "Not available"}</span>
              </div>
              {fields.map((f, i) => {
                const q = snaps[i];
                const v = values[i];
                return (
                  <div role="cell" className={s.cell} key={f.id}>
                    {q?.isPending ? (
                      <Skeleton height={24} width="60%" />
                    ) : q?.isError ? (
                      <span className={s.cellNa}>{friendlyMessage(q.error)}</span>
                    ) : v ? (
                      <>
                        <span className={s.cellBig}>{fmt(v.value, row.decimals)}</span>
                        <MeterBar percent={(Math.abs(v.value) / max) * 100} color={row.color} height={6} />
                      </>
                    ) : (
                      <span className={s.cellNa}>Not available</span>
                    )}
                  </div>
                );
              })}
            </div>
          );
        })}

      </div>
    </div>
  );
}
