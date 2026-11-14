import type { DatasetRef } from "@/shared/api";
import { SectionTitle } from "@/shared/ui/layout";
import { pixelText } from "../lib/strategies";
import s from "./analysis.module.css";

/** "Data used": every dataset with its provider, pixel size and period. */
export function DatasetList({ datasets }: { datasets: readonly DatasetRef[] }) {
  return (
    <section className={s.datasets} aria-labelledby="data-used">
      <SectionTitle id="data-used">Data used</SectionTitle>
      <ul className={s.datasetList}>
        {datasets.map((d) => (
          <li key={`${d.provider}-${d.dataset}`} className={s.datasetRow}>
            <div>
              <div className={s.datasetName}>
                {d.url ? (
                  <a href={d.url} target="_blank" rel="noreferrer">
                    {d.dataset}
                  </a>
                ) : (
                  d.dataset
                )}
              </div>
              <div className={s.small}>{d.provider}</div>
            </div>
            <div className={s.datasetMeta}>
              {pixelText(d.resolution_m)}
              {d.coverage_period && (
                <>
                  <br />
                  {d.coverage_period}
                </>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
