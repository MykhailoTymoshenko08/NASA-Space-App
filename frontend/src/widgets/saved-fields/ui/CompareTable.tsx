import { useState, type CSSProperties } from "react";
import type { ComparedField, ComparisonRow, FieldComparison } from "@/entities/comparison";
import { QUALITY } from "@/entities/metric";
import { Icon } from "@/shared/ui/icon";
import { MeterBar } from "@/shared/ui/progress";
import {
  barPercents,
  cellsInOrder,
  compareValue,
  hasValue,
  NEVER_FOLD,
  rowsByGroup,
  sharedCellNote,
  sharedQuality,
} from "../lib/compare";
import { FieldLetter } from "./FieldLetter";
import s from "./compare.module.css";

const cx = (...c: (string | false | undefined)[]) => c.filter(Boolean).join(" ");

/** "Best 6.0 to 7.0" for `better: "target"` rows. */
const targetText = (row: ComparisonRow) =>
  row.target ? `Best ${compareValue(row.target.min, row.unit).value} to ${compareValue(row.target.max, row.unit).value}` : null;

const folds = (row: ComparisonRow) => row.same_for_all && !NEVER_FOLD.has(row.group);

function Row({ row, fields }: { row: ComparisonRow; fields: readonly ComparedField[] }) {
  const cells = cellsInOrder(row, fields.map((f) => f.saved_field_id));
  const bars = barPercents(row, cells);
  const shared = sharedCellNote(row);
  const quality = row.group === "money" ? null : sharedQuality(row);
  const target = targetText(row);
  return (
    <div role="row" className={s.row}>
      <div role="rowheader" className={s.rowHead}>
        <span className={s.rowLabel}>{row.label}</span>
        {target && <span className={s.rowNote}>{target}</span>}
        {row.same_for_all && <span className={s.rowNote}>Same for all fields</span>}
        {row.note && <span className={s.rowNote}>{row.note}</span>}
        {(quality || shared) && <span className={s.rowNote}>{[quality && QUALITY[quality].label, shared].filter(Boolean).join(". ")}</span>}
      </div>
      {cells.map((c, i) => {
        const field = fields[i]!;
        const best = !!c && row.best.includes(c.saved_field_id);
        const shown = hasValue(c) ? compareValue(c.value, row.unit) : null;
        const loss = hasValue(c) && typeof c.value === "number" && c.value < 0 && row.unit.startsWith("USD");
        return (
          <div role="cell" key={field.saved_field_id} className={cx(s.cell, best && s.best)}>
            <span className={s.cellField} aria-hidden="true">
              <FieldLetter label={field.label} size="sm" />
              {field.name}
            </span>
            {shown ? (
              <>
                <span className={s.value}>
                  <span className={cx(typeof c?.value === "string" ? s.valueText : s.valueNum, loss && s.loss)}>{shown.value}</span>
                  {(shown.unit || loss) && (
                    <span className={s.unit}>
                      {shown.unit && ` ${shown.unit}`}
                      {loss && " (loss)"}
                    </span>
                  )}
                </span>
                {bars?.[i] != null && (
                  <MeterBar percent={bars[i]} height={6} color={best ? "var(--color-green-700)" : "var(--color-green-300)"} />
                )}
              </>
            ) : (
              <span className={s.na}>Not available</span>
            )}
            {best && (
              <span className={s.bestTag}>
                <Icon name="check" size={14} />
                Best
              </span>
            )}
            {shown && !quality && row.group !== "money" && <span className={s.cellNote}>{QUALITY[c!.quality].label}</span>}
            {c?.note && !shown && <span className={s.cellNote}>{c.note}</span>}
            {c?.note && shown && !shared && (
              <details className={s.dataNote}>
                <summary>Data notes</summary>
                <p>{c.note}</p>
              </details>
            )}
          </div>
        );
      })}
    </div>
  );
}

/**
 * Every comparison row, grouped (money, land, soil, history, climate). The server's best cell of a ranked
 * row is tinted and labelled "Best". Rows that are the same for every field fold into one line, except money.
 */
export function CompareTable({ data }: { data: FieldComparison }) {
  const [showSame, setShowSame] = useState(false);
  const same = data.rows.filter(folds);
  const visible = showSame ? data.rows : data.rows.filter((r) => !folds(r));
  const groups = rowsByGroup(visible);
  const cols = data.fields.length;

  return (
    <section className={s.tableWrap} aria-labelledby="compare-table-title">
      <div className={s.tableTitle}>
        <h2 id="compare-table-title" className={s.h2}>
          Side by side
        </h2>
        <span className={s.muted}>
          <span className={s.legendBest} aria-hidden="true" /> Best in the row
        </span>
      </div>
      <div
        role="table"
        aria-label="Comparison of selected fields"
        className={cx(s.table, cols > 2 && s.tableMany)}
        style={{ "--cols": cols } as CSSProperties}
      >
        <div role="rowgroup" className={s.head}>
          <div role="row" className={s.row}>
            <div role="columnheader" className={s.headLabel}>
              Measure
            </div>
            {data.fields.map((f) => (
              <div role="columnheader" key={f.saved_field_id} className={s.headCell}>
                <FieldLetter label={f.label} size="sm" />
                <span className={s.headName}>
                  <span className="visually-hidden">Field {f.label}:</span>{" "}
                  {f.name}
                </span>
              </div>
            ))}
          </div>
        </div>
        {groups.map((g) => (
          <div role="rowgroup" key={g.key}>
            <div role="row" className={s.groupRow}>
              <div role="rowheader" aria-colspan={cols + 1} className={s.groupHead}>
                <span className={s.groupTitle}>{g.title}</span>
                {g.lead && <span className={s.groupLead}>{g.lead}</span>}
              </div>
            </div>
            {g.rows.map((row) => (
              <Row key={row.key} row={row} fields={data.fields} />
            ))}
          </div>
        ))}
      </div>
      {same.length > 0 && (
        <div className={s.same}>
          {!showSame && (
            <p className={s.muted}>
              <strong>Same for every field:</strong>{" "}
              {same
                .map((r) => {
                  const c = r.cells[0];
                  const v = hasValue(c) ? compareValue(c.value, r.unit) : null;
                  return v ? `${r.label} (${[v.value, v.unit].filter(Boolean).join(" ")})` : r.label;
                })
                .join("; ")}
              .
            </p>
          )}
          <button type="button" className={s.linkButton} aria-expanded={showSame} onClick={() => setShowSame((v) => !v)}>
            {showSame
              ? `Hide ${same.length === 1 ? "the row that is" : "rows that are"} the same`
              : same.length === 1
                ? "Show the row that is the same"
                : `Show ${same.length} rows that are the same`}
          </button>
        </div>
      )}
    </section>
  );
}
