import { useState, type MouseEvent } from "react";
import type { TimeSeries } from "@/shared/api";
import { formatDate, toDisplayNumber } from "@/shared/lib";
import { datasetSource } from "../lib/strategies";
import s from "./analysis.module.css";

const W = 480;
const L = 46;
const T = 14;
const PW = 420;
const PH = 146;
const BASE = T + PH;

/** One hue per measure (DS chart colors). */
function colorFor(key: string): string {
  if (key.includes("precip") || key.includes("rain")) return "var(--color-data-rain)";
  if (key.includes("soil_moisture") || key.includes("wetness")) return "var(--color-data-soil)";
  if (key.includes("temp")) return "var(--color-data-temp)";
  if (key.includes("humidity")) return "var(--color-data-humidity)";
  return "var(--color-data-nitrogen)";
}

const isBarSeries = (ts: TimeSeries) => ts.unit === "mm" || ts.key.includes("precip");

const fmt = (v: number, decimals: number) =>
  v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });

/**
 * Line (or bar, for rain totals) chart of one TimeSeries in US units.
 * Hover or tap reads out one point; the aria-label is the text alternative.
 */
export function TimeSeriesChart({ series }: { series: TimeSeries }) {
  const [hi, setHi] = useState<number | null>(null);
  const pts = series.points.map((p) => ({ t: p.t, v: p.v === null ? null : toDisplayNumber(p.v, series.unit).value }));
  const unit = toDisplayNumber(0, series.unit).unit;
  const unitSuffix = unit ? ` ${unit}` : "";
  const values = pts.map((p) => p.v).filter((v): v is number => v !== null);
  const n = pts.length;

  if (n === 0 || values.length === 0) {
    return (
      <div className={s.chartCard}>
        <ChartHead series={series} readout="Not available" when="" />
        <p className={s.muted}>No values in this period.</p>
      </div>
    );
  }

  const bar = isBarSeries(series);
  const lo = bar ? 0 : Math.min(...values);
  const hiV = Math.max(...values);
  const pad = (hiV - lo) * 0.1 || 1;
  const min = bar ? 0 : lo - pad;
  const max = hiV + pad;
  const decimals = max - min < 2 ? 2 : max - min < 20 ? 1 : 0;
  const xs = (i: number) => L + (n === 1 ? PW / 2 : (PW * i) / (n - 1));
  const ys = (v: number) => BASE - (PH * (v - min)) / (max - min);
  const color = colorFor(series.key);

  // Line: break the path where values are missing (never draw through gaps).
  let line = "";
  pts.forEach((p, i) => {
    if (p.v === null) return;
    const prev = i > 0 ? pts[i - 1]?.v : null;
    line += `${prev === null || prev === undefined ? "M" : "L"}${xs(i).toFixed(1)},${ys(p.v).toFixed(1)}`;
  });
  const bw = Math.max(2, (PW / n) * 0.55);

  const lastIdx = pts.map((p) => p.v).lastIndexOf(values[values.length - 1]!);
  const idx = hi ?? lastIdx;
  const cur = pts[idx];
  const readout = cur?.v == null ? "No value" : `${fmt(cur.v, decimals)}${unitSuffix}`;
  const ticks = [0, 1, 2].map((k) => min + ((max - min) * k) / 2);
  const mid = pts[Math.floor((n - 1) / 2)];

  const onMove = (e: MouseEvent<SVGRectElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const i = Math.round(((e.clientX - r.left) / r.width) * (n - 1));
    setHi(Math.max(0, Math.min(n - 1, i)));
  };

  const alt =
    `${series.label} from ${formatDate(pts[0]!.t)} to ${formatDate(pts[n - 1]!.t)}. ` +
    `Lowest ${fmt(Math.min(...values), decimals)}${unitSuffix}, highest ${fmt(hiV, decimals)}${unitSuffix}, ` +
    `latest ${fmt(values[values.length - 1]!, decimals)}${unitSuffix}.`;

  return (
    <div className={s.chartCard}>
      <ChartHead series={series} readout={readout} when={cur ? formatDate(cur.t) : ""} />
      <svg viewBox={`0 0 ${W} 190`} width="100%" role="img" aria-label={alt} className={s.chart}>
        {ticks.map((v) => (
          <g key={v}>
            <path d={`M${L},${ys(v).toFixed(1)}H${L + PW}`} className={s.gridLine} />
            <text x={40} y={(ys(v) + 4).toFixed(1)} className={s.tick} textAnchor="end">
              {fmt(v, decimals)}
            </text>
          </g>
        ))}
        <text x={L} y={184} className={s.tick}>
          {formatDate(pts[0]!.t)}
        </text>
        {mid && n > 2 && (
          <text x={L + PW / 2} y={184} className={s.tick} textAnchor="middle">
            {formatDate(mid.t)}
          </text>
        )}
        <text x={L + PW} y={184} className={s.tick} textAnchor="end">
          {formatDate(pts[n - 1]!.t)}
        </text>
        {bar ? (
          pts.map((p, i) =>
            p.v !== null && p.v > 0 ? (
              <rect
                key={i}
                x={xs(i) - bw / 2}
                y={ys(p.v)}
                width={bw}
                height={BASE - ys(p.v)}
                rx={2}
                style={{ fill: color, opacity: hi === null || hi === i ? 1 : 0.55 }}
              />
            ) : null,
          )
        ) : (
          <path d={line} style={{ stroke: color }} className={s.line} />
        )}
        {hi !== null && <path d={`M${xs(idx).toFixed(1)},${T}V${BASE}`} className={s.cross} />}
        {!bar && cur?.v != null && (
          <circle cx={xs(idx)} cy={ys(cur.v)} r={5} style={{ fill: color }} className={s.dot} />
        )}
        <rect
          x={L}
          y={T}
          width={PW}
          height={PH}
          className={s.hit}
          onMouseMove={onMove}
          onClick={onMove}
          onMouseLeave={() => setHi(null)}
        />
      </svg>
    </div>
  );
}

function ChartHead({ series, readout, when }: { series: TimeSeries; readout: string; when: string }) {
  return (
    <div className={s.chartHead}>
      <div>
        <h3 className={s.chartTitle}>{series.label}</h3>
        {series.source && <div className={s.small}>{datasetSource(series.source)}</div>}
      </div>
      <div className={s.readout} aria-live="off">
        <div className={s.readoutValue}>{readout}</div>
        <div className={s.small}>{when}</div>
      </div>
    </div>
  );
}
