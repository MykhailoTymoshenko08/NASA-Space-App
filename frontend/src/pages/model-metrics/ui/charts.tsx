import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { SegmentedControl } from "@/shared/ui/choice";
import {
  CONFUSION,
  CROPS,
  DRIVERS,
  METHODS,
  RELIABILITY_AFTER,
  RELIABILITY_BEFORE,
  STATES,
  YEARS,
  type ReliabilityBin,
} from "../model/metrics";
import s from "./model-metrics.module.css";

export const pct = (v: number, digits = 1) => `${(v * 100).toFixed(digits)}%`;
const pts = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(1)} pts`;
const num = (v: number) => v.toLocaleString("en-US");

/* ---------- Hover tooltip: one per chart, follows the pointer inside the chart frame ---------- */

type Tip = { x: number; y: number; content: ReactNode } | null;

function useTip() {
  const frame = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<Tip>(null);
  const bind = useCallback(
    (content: ReactNode) => ({
      onPointerMove: (e: PointerEvent) => {
        const box = frame.current?.getBoundingClientRect();
        if (!box) return;
        setTip({ x: e.clientX - box.left, y: e.clientY - box.top, content });
      },
      onPointerLeave: () => setTip(null),
    }),
    [],
  );
  const flip = tip && frame.current ? tip.x > frame.current.clientWidth * 0.6 : false;
  const node = tip ? (
    <div
      className={s.tip}
      role="presentation"
      style={{ left: tip.x, top: tip.y, transform: `translate(${flip ? "calc(-100% - 14px)" : "14px"}, -50%)` }}
    >
      {tip.content}
    </div>
  ) : null;
  return { frame, bind, node };
}

function TipRow({ swatch, label, value }: { swatch?: string; label: string; value: string }) {
  return (
    <div className={s.tipRow}>
      {swatch && <span className={s.tipSwatch} style={{ background: swatch }} aria-hidden="true" />}
      <span className={s.tipLabel}>{label}</span>
      <span className={s.tipValue}>{value}</span>
    </div>
  );
}

function Legend({ items }: { items: { label: string; color: string; shape?: "dot" | "bar" | "dash" }[] }) {
  return (
    <ul className={s.legend}>
      {items.map((i) => (
        <li key={i.label}>
          <span className={`${s.legendKey} ${s[i.shape ?? "bar"]}`} style={{ "--key": i.color } as CSSProperties} />
          {i.label}
        </li>
      ))}
    </ul>
  );
}

/** Same numbers as a table, for screen readers and anyone who prefers rows. */
export function TableView({ caption, head, rows }: { caption: string; head: string[]; rows: (string | number)[][] }) {
  return (
    <details className={s.tableView}>
      <summary>Show as a table</summary>
      <div className={s.tableScroll}>
        <table>
          <caption className="visually-hidden">{caption}</caption>
          <thead>
            <tr>
              {head.map((h) => (
                <th key={h} scope="col">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {r.map((c, j) =>
                  j === 0 ? (
                    <th key={j} scope="row">
                      {c}
                    </th>
                  ) : (
                    <td key={j}>{c}</td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

/* ---------- 1. Model vs simple rules ---------- */

type MethodMetric = "top1" | "top3" | "macroF1";
const METRIC_OPTIONS = [
  { value: "top1", label: "First pick right" },
  { value: "top3", label: "Right crop in top 3" },
  { value: "macroF1", label: "Rare-crop quality" },
] as const satisfies readonly { value: MethodMetric; label: string }[];

const METRIC_HELP: Record<MethodMetric, string> = {
  top1: "Share of field-seasons where the first crop named is the one that really grew.",
  top3: "Share of field-seasons where the real crop is among the three named. Every rule scores high here: there are only five crops.",
  macroF1: "Macro-F1 (0 to 1): accuracy averaged over the five crops equally, so sorghum and alfalfa count as much as corn.",
};

export function MethodChart() {
  const [metric, setMetric] = useState<MethodMetric>("top1");
  const { frame, bind, node } = useTip();
  const fmt = (v: number) => (metric === "macroF1" ? v.toFixed(2) : pct(v));
  return (
    <div className={s.chartBlock}>
      <div className={s.controls}>
        <SegmentedControl label="Measure" options={METRIC_OPTIONS} value={metric} onChange={setMetric} />
      </div>
      <p className={s.chartHelp}>{METRIC_HELP[metric]}</p>
      <div ref={frame} className={s.frame}>
        <ul className={s.hbars} aria-label="Score by method">
          {METHODS.map((m) => {
            const v = m[metric];
            return (
              <li key={m.key} className={s.hbarRow}>
                <div className={s.hbarHead}>
                  <span className={m.isModel ? s.hbarNameModel : s.hbarName}>{m.label}</span>
                  <span className={s.hbarNote}>{m.note}</span>
                </div>
                <div
                  className={s.hbarTrack}
                  {...bind(
                    <>
                      <div className={s.tipTitle}>{m.label}</div>
                      <TipRow label="First pick right" value={pct(m.top1)} />
                      <TipRow label="Right crop in top 3" value={pct(m.top3)} />
                      <TipRow label="Rare-crop quality" value={m.macroF1.toFixed(2)} />
                    </>,
                  )}
                >
                  <span
                    className={s.hbar}
                    style={{
                      width: `${v * 100}%`,
                      background: m.isModel ? "var(--color-chart-model)" : "var(--color-chart-muted)",
                    }}
                  />
                </div>
                <span className={m.isModel ? s.hbarValueModel : s.hbarValue}>{fmt(v)}</span>
              </li>
            );
          })}
        </ul>
        <div className={s.hbarAxis} aria-hidden="true">
          {[0, 0.25, 0.5, 0.75, 1].map((t) => (
            <span key={t} style={{ left: `${t * 100}%` }}>
              {metric === "macroF1" ? t.toFixed(2) : `${t * 100}%`}
            </span>
          ))}
        </div>
        {node}
      </div>
      <TableView
        caption="Score by method, validated on unseen fields"
        head={["Method", "First pick right", "Right crop in top 3", "Macro-F1"]}
        rows={METHODS.map((m) => [m.label, pct(m.top1), pct(m.top3), m.macroF1.toFixed(2)])}
      />
    </div>
  );
}

/* ---------- 2. By state: alternation vs model (dumbbell) ---------- */

export function StateChart() {
  const { frame, bind, node } = useTip();
  return (
    <div className={s.chartBlock}>
      <Legend
        items={[
          { label: "Corn–soy alternation", color: "var(--color-chart-baseline)", shape: "dot" },
          { label: "Our model", color: "var(--color-chart-model)", shape: "dot" },
        ]}
      />
      <div ref={frame} className={s.frame}>
        <ul className={s.dumbbells} aria-label="First pick right, by state">
          {STATES.map((st) => {
            const gain = st.model - st.alternation;
            const big = gain > 0.1;
            return (
              <li
                key={st.code}
                className={s.dbRow}
                {...bind(
                  <>
                    <div className={s.tipTitle}>
                      {st.name} · {num(st.rows)} field-seasons
                    </div>
                    <TipRow swatch="var(--color-chart-model)" label="Our model" value={pct(st.model)} />
                    <TipRow swatch="var(--color-chart-baseline)" label="Alternation" value={pct(st.alternation)} />
                    <TipRow label="Gain" value={pts(gain)} />
                  </>,
                )}
              >
                <span className={s.dbName}>
                  {st.name}
                  <span className={s.dbCode}>{st.code}</span>
                </span>
                <div className={s.dbTrack}>
                  <span
                    className={s.dbLine}
                    style={{ left: `${st.alternation * 100}%`, width: `${gain * 100}%` }}
                  />
                  <span
                    className={s.dbDot}
                    style={{ left: `${st.alternation * 100}%`, background: "var(--color-chart-baseline)" }}
                  />
                  <span className={s.dbDot} style={{ left: `${st.model * 100}%`, background: "var(--color-chart-model)" }} />
                </div>
                <span className={big ? s.dbGainBig : s.dbGain}>{pts(gain)}</span>
              </li>
            );
          })}
        </ul>
        <div className={s.dbAxis} aria-hidden="true">
          {[0, 0.25, 0.5, 0.75, 1].map((t) => (
            <span key={t} style={{ left: `${t * 100}%` }}>
              {t * 100}%
            </span>
          ))}
        </div>
        {node}
      </div>
      <TableView
        caption="First pick right, by state"
        head={["State", "Field-seasons", "Our model", "Alternation", "Gain"]}
        rows={STATES.map((st) => [st.name, num(st.rows), pct(st.model), pct(st.alternation), pts(st.model - st.alternation)])}
      />
    </div>
  );
}

/* ---------- 3. Reliability diagram ---------- */

const PAD = { l: 56, r: 16, t: 16, b: 48, min: 0.2, max: 1 };

/** Plot size in CSS pixels, so text stays 12 px at every width. Height follows width within 300-420. */
function usePlotSize(frame: RefObject<HTMLDivElement | null>) {
  const [w, setW] = useState(820);
  useLayoutEffect(() => {
    const el = frame.current;
    if (!el) return;
    const measure = () => el.clientWidth > 0 && setW(el.clientWidth);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [frame]);
  const h = Math.round(Math.min(420, Math.max(300, w * 0.5)));
  const R = { ...PAD, w, h };
  const span = PAD.max - PAD.min;
  return {
    R,
    rx: (v: number) => R.l + ((v - R.min) / span) * (R.w - R.l - R.r),
    ry: (v: number) => R.h - R.b - ((v - R.min) / span) * (R.h - R.t - R.b),
  };
}
const binLabel = (bin: string) =>
  bin
    .split("–")
    .map((v) => `${Math.round(Number(v) * 100)}%`)
    .join("–");
// The 0.2-0.3 bin holds 2 and 6 rows: too few to plot as a point.
const plotted = (bins: readonly ReliabilityBin[]) => bins.filter((b) => b.n >= 30);

export function ReliabilityChart() {
  const { frame, bind, node } = useTip();
  const { R, rx, ry } = usePlotSize(frame);
  const narrow = R.w < 520;
  const series = [
    { key: "before", label: "Before calibration", color: "var(--color-chart-baseline)", bins: plotted(RELIABILITY_BEFORE) },
    { key: "after", label: "After calibration", color: "var(--color-chart-model)", bins: plotted(RELIABILITY_AFTER) },
  ];
  const ticks = narrow ? [0.2, 0.6, 1] : [0.2, 0.4, 0.6, 0.8, 1];
  return (
    <div className={s.chartBlock}>
      <Legend
        items={[
          ...series.map((x) => ({ label: x.label, color: x.color, shape: "dot" as const })),
          { label: "Perfectly honest", color: "var(--color-line-control)", shape: "dash" as const },
        ]}
      />
      <div ref={frame} className={s.frame}>
        <svg viewBox={`0 0 ${R.w} ${R.h}`} width={R.w} height={R.h} className={s.svg} role="img" aria-label="Stated confidence against how often the model was right, before and after calibration">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={R.l} x2={R.w - R.r} y1={ry(t)} y2={ry(t)} className={s.grid} />
              <text x={R.l - 8} y={ry(t)} className={s.axisText} textAnchor="end" dominantBaseline="middle">
                {t * 100}%
              </text>
              <text x={rx(t)} y={R.h - R.b + 18} className={s.axisText} textAnchor="middle">
                {t * 100}%
              </text>
            </g>
          ))}
          <text x={(R.l + R.w - R.r) / 2} y={R.h - 4} className={s.axisTitle} textAnchor="middle">
            Confidence the model stated
          </text>
          <text
            transform={`translate(12 ${(R.t + R.h - R.b) / 2}) rotate(-90)`}
            className={s.axisTitle}
            textAnchor="middle"
          >
            How often it was right
          </text>
          <line x1={rx(R.min)} y1={ry(R.min)} x2={rx(R.max)} y2={ry(R.max)} className={s.diagonal} />
          {series.map((x) => (
            <g key={x.key}>
              <polyline
                points={x.bins.map((b) => `${rx(b.predicted)},${ry(b.observed)}`).join(" ")}
                fill="none"
                stroke={x.color}
                strokeWidth={2}
                strokeLinejoin="round"
              />
              {x.bins.map((b) => (
                <g
                  key={b.bin}
                  {...bind(
                    <>
                      <div className={s.tipTitle}>
                        {x.label} · confidence {binLabel(b.bin)}
                      </div>
                      <TipRow swatch={x.color} label="Stated" value={pct(b.predicted)} />
                      <TipRow label="Right" value={pct(b.observed)} />
                      <TipRow label="Field-seasons" value={num(b.n)} />
                    </>,
                  )}
                >
                  <circle cx={rx(b.predicted)} cy={ry(b.observed)} r={14} fill="transparent" />
                  <circle cx={rx(b.predicted)} cy={ry(b.observed)} r={5} fill={x.color} stroke="var(--color-surface)" strokeWidth={2} />
                </g>
              ))}
            </g>
          ))}
          <text x={rx(0.22)} y={ry(0.95)} className={s.zoneLabel}>
            {narrow ? "Above: too modest" : "Above the line: too modest"}
          </text>
          <text x={rx(0.99)} y={ry(0.3)} className={s.zoneLabel} textAnchor="end">
            {narrow ? "Below: overconfident" : "Below the line: overconfident"}
          </text>
        </svg>
        {node}
      </div>
      <TableView
        caption="Reliability of the first pick by confidence bin"
        head={["Confidence bin", "Before: stated", "Before: right", "After: stated", "After: right", "After: field-seasons"]}
        rows={RELIABILITY_AFTER.map((a, i) => {
          const b = RELIABILITY_BEFORE[i];
          return [a.bin, b ? pct(b.predicted) : "–", b ? pct(b.observed) : "–", pct(a.predicted), pct(a.observed), num(a.n)];
        })}
      />
    </div>
  );
}

/* ---------- 4. Confusion matrix (row-normalized) ---------- */

export function ConfusionChart() {
  const { frame, bind, node } = useTip();
  return (
    <div className={s.chartBlock}>
      <div ref={frame} className={s.frame}>
        <div className={s.cmScroll}>
          <div className={s.cm} role="img" aria-label="Confusion matrix: rows are the crop that grew, columns the model's first pick; the table below has the numbers">
            <span className={s.cmCorner}>
              Grew <span aria-hidden="true">↓</span> · Picked <span aria-hidden="true">→</span>
            </span>
            {CROPS.map((c) => (
              <span key={c.key} className={s.cmColHead}>
                {c.label}
              </span>
            ))}
            {CROPS.map((row, i) => {
              const counts = CONFUSION[i] ?? [];
              const total = counts.reduce((a, b) => a + b, 0);
              return [
                <span key={`${row.key}-h`} className={s.cmRowHead}>
                  {row.label}
                  <span className={s.cmRowN}>{num(total)}</span>
                </span>,
                ...counts.map((n, j) => {
                  const share = n / total;
                  const diag = i === j;
                  const col = CROPS[j];
                  return (
                    <span
                      key={`${row.key}-${j}`}
                      className={`${s.cmCell} ${diag ? s.cmDiag : ""}`}
                      style={
                        {
                          "--share": `${Math.round(Math.min(1, share) * 92 + (share > 0 ? 4 : 0))}%`,
                          color: share > 0.45 ? "var(--color-white)" : "var(--color-ink)",
                        } as CSSProperties
                      }
                      {...bind(
                        <>
                          <div className={s.tipTitle}>
                            Grew {row.label.toLowerCase()}, picked {col?.label.toLowerCase()}
                          </div>
                          <TipRow label="Field-seasons" value={num(n)} />
                          <TipRow label={`Share of real ${row.label.toLowerCase()}`} value={pct(share)} />
                        </>,
                      )}
                    >
                      {pct(share, 0)}
                    </span>
                  );
                }),
              ];
            })}
          </div>
        </div>
        {node}
      </div>
      <TableView
        caption="Confusion matrix in field-seasons; rows are the crop that grew"
        head={["Grew \\ Picked", ...CROPS.map((c) => c.label)]}
        rows={CROPS.map((c, i) => [c.label, ...(CONFUSION[i] ?? []).map(num)])}
      />
    </div>
  );
}

/* ---------- 5. Stability by year ---------- */

const ALTERNATION_TOP1 = METHODS.find((m) => m.key === "alternation")?.top1 ?? 0;

export function YearChart() {
  const { frame, bind, node } = useTip();
  return (
    <div className={s.chartBlock}>
      <div ref={frame} className={s.frame}>
        <div className={s.cols}>
          <div className={s.colsPlot}>
            {[0.25, 0.5, 0.75, 1].map((t) => (
              <span key={t} className={s.colsGrid} style={{ bottom: `${t * 100}%` }}>
                <span>{t * 100}%</span>
              </span>
            ))}
            <span className={s.colsRef} style={{ bottom: `${ALTERNATION_TOP1 * 100}%` }}>
              <span>Corn–soy alternation, all years {pct(ALTERNATION_TOP1)}</span>
            </span>
            {YEARS.map((y) => (
              <div
                key={y.year}
                className={s.colSlot}
                {...bind(
                  <>
                    <div className={s.tipTitle}>Tested on {y.year}</div>
                    <TipRow swatch="var(--color-chart-model)" label="First pick right" value={pct(y.top1)} />
                    <TipRow label="Macro-F1" value={y.macroF1.toFixed(2)} />
                    <TipRow label="Field-seasons" value={num(y.rows)} />
                  </>,
                )}
              >
                <span className={s.colValue}>{pct(y.top1, 0)}</span>
                <span className={s.col} style={{ height: `${y.top1 * 100}%` }} />
              </div>
            ))}
          </div>
          <div className={s.colsLabels} aria-hidden="true">
            {YEARS.map((y) => (
              <span key={y.year}>{y.year}</span>
            ))}
          </div>
        </div>
        {node}
      </div>
      <TableView
        caption="Leave one year out: first pick right by test year"
        head={["Test year", "Field-seasons", "First pick right", "Macro-F1"]}
        rows={YEARS.map((y) => [y.year, num(y.rows), pct(y.top1), y.macroF1.toFixed(2)])}
      />
    </div>
  );
}

/* ---------- 6. What drives the prediction ---------- */

export function DriversChart() {
  const { frame, bind, node } = useTip();
  const max = Math.max(...DRIVERS.map((d) => d.share));
  return (
    <div className={s.chartBlock}>
      <div ref={frame} className={s.frame}>
        <ol className={s.drivers}>
          {DRIVERS.map((d, i) => (
            <li
              key={d.feature}
              className={s.driver}
              {...bind(
                <>
                  <div className={s.tipTitle}>{d.label}</div>
                  <TipRow swatch="var(--color-chart-model)" label="Share of influence" value={pct(d.share)} />
                  <TipRow label="Moves most" value={d.crop} />
                  <div className={s.tipNote}>{d.hint}</div>
                </>,
              )}
            >
              <span className={s.driverRank}>{String(i + 1).padStart(2, "0")}</span>
              <div className={s.driverBody}>
                <div className={s.driverHead}>
                  <span className={s.driverName}>{d.label}</span>
                  <span className={s.driverValue}>{pct(d.share)}</span>
                </div>
                <div className={s.driverTrack}>
                  <span className={s.driverBar} style={{ width: `${(d.share / max) * 100}%` }} />
                </div>
                <span className={s.driverHint}>{d.hint}</span>
              </div>
            </li>
          ))}
        </ol>
        {node}
      </div>
      <TableView
        caption="Top 15 features by mean absolute SHAP share"
        head={["Feature", "Share of influence", "Crop it moves most", "Direction"]}
        rows={DRIVERS.map((d) => [d.label, pct(d.share), d.crop, d.hint])}
      />
    </div>
  );
}

/* ---------- Training mix: one segmented bar ---------- */

const MIX_SHADES = ["100%", "78%", "58%", "40%", "24%"];

export function CropMix() {
  const total = CROPS.reduce((a, c) => a + c.rows, 0);
  return (
    <div className={s.mix}>
      <div className={s.mixBar} role="img" aria-label={CROPS.map((c) => `${c.label} ${pct(c.rows / total)}`).join(", ")}>
        {CROPS.map((c, i) => (
          <span
            key={c.key}
            className={s.mixSeg}
            style={{ flexGrow: c.rows, "--shade": MIX_SHADES[i] } as CSSProperties}
            title={`${c.label}: ${num(c.rows)} field-seasons`}
          />
        ))}
      </div>
      <ul className={s.mixLegend}>
        {CROPS.map((c, i) => (
          <li key={c.key}>
            <span className={s.mixKey} style={{ "--shade": MIX_SHADES[i] } as CSSProperties} aria-hidden="true" />
            <span className={s.mixName}>{c.label}</span>
            <span className={s.mixNum}>
              {num(c.rows)} · {pct(c.rows / total, 0)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
