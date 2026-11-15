import type { ReactNode } from "react";
import { ROUTES } from "@/shared/config";
import { useDocumentTitle } from "@/shared/lib";
import { ButtonLink } from "@/shared/ui/button";
import { Icon } from "@/shared/ui/icon";
import { Container, Eyebrow } from "@/shared/ui/layout";
import { CALIBRATION, CROPS, DATASET, FOLDS, GAIN, LIMITS, LITERATURE_CHECK, METHODS, STATES, TRAINED_ON } from "../model/metrics";
import {
  ConfusionChart,
  CropMix,
  DriversChart,
  MethodChart,
  ReliabilityChart,
  StateChart,
  YearChart,
  pct,
} from "./charts";
import s from "./model-metrics.module.css";

const model = METHODS.find((m) => m.isModel) ?? METHODS[0]!;
const alternation = METHODS.find((m) => m.key === "alternation") ?? METHODS[1]!;
const kansas = STATES.find((x) => x.code === "KS")!;
const sorghum = CROPS.find((c) => c.key === "sorghum")!;
const trainedOn = new Date(`${TRAINED_ON}T12:00:00`).toLocaleDateString("en-US", {
  day: "numeric",
  month: "long",
  year: "numeric",
});

function Stat({ value, label, sub, accent }: { value: string; label: string; sub: ReactNode; accent?: boolean }) {
  return (
    <div className={`${s.stat} ${accent ? s.statAccent : ""}`}>
      <span className={s.statValue}>{value}</span>
      <span className={s.statLabel}>{label}</span>
      <span className={s.statSub}>{sub}</span>
    </div>
  );
}

function Section({
  id,
  n,
  title,
  lead,
  chart,
  notes,
}: {
  id: string;
  n: string;
  title: string;
  lead: ReactNode;
  chart: ReactNode;
  notes?: ReactNode;
}) {
  return (
    <Container as="section" id={id} className={s.section} aria-labelledby={`${id}-title`}>
      <header className={s.sectionHead}>
        <span className={s.sectionNum} aria-hidden="true">
          {n}
        </span>
        <div>
          <h2 id={`${id}-title`} className={s.sectionTitle}>
            {title}
          </h2>
          <p className={s.sectionLead}>{lead}</p>
        </div>
      </header>
      <div className={notes ? s.sectionGrid : undefined}>
        <div className={s.chartPanel}>{chart}</div>
        {notes && <aside className={s.notes}>{notes}</aside>}
      </div>
    </Container>
  );
}

function Note({ title, children, tone }: { title: string; children: ReactNode; tone?: "info" | "warning" }) {
  return (
    <div className={`${s.note} ${tone ? s[tone] : ""}`}>
      <h3 className={s.noteTitle}>
        {tone && <Icon name={tone === "warning" ? "warning" : "info"} size={18} />}
        {title}
      </h3>
      <div className={s.noteBody}>{children}</div>
    </div>
  );
}

export function ModelMetricsPage() {
  useDocumentTitle("Model accuracy");

  return (
    <>
      <Container as="section" className={s.hero} aria-labelledby="page-title">
        <Eyebrow>Crop model · validation report</Eyebrow>
        <h1 id="page-title" className={s.heroTitle}>
          How often does the model get the crop right?
        </h1>
        <p className={s.heroLead}>
          For each field, the model names the crop most likely to grow there next season. We checked it on{" "}
          {DATASET.fields.toLocaleString("en-US")} real fields it never saw in training, against the simple rules farmers
          already use. Every number on this page comes from that test.
        </p>
        <ul className={s.meta} aria-label="About this model">
          <li>
            <Icon name="check" size={16} /> Trained {trainedOn}
          </li>
          <li>{DATASET.fieldSeasons.toLocaleString("en-US")} field-seasons, {DATASET.seasons}</li>
          <li>{DATASET.states.join(", ")}</li>
          <li>{DATASET.features} features: crop history, weather, soil</li>
          <li>{CROPS.length} crops</li>
        </ul>

        <div className={s.stats}>
          <Stat
            accent
            value={pct(model.top1)}
            label="first pick right"
            sub={<>Corn–soy alternation: {pct(alternation.top1)}</>}
          />
          <Stat
            value={`+${(GAIN.value * 100).toFixed(1)}`}
            label="points over alternation"
            sub={
              <>
                95% interval +{(GAIN.ci95[0] * 100).toFixed(1)} to +{(GAIN.ci95[1] * 100).toFixed(1)}
              </>
            }
          />
          <Stat value={pct(model.top3)} label="real crop in its top 3" sub="Of the five crops it ranks" />
          <Stat
            value={CALIBRATION.after.ece.toFixed(3)}
            label="calibration error"
            sub={<>Was {CALIBRATION.before.ece.toFixed(3)} before calibration</>}
          />
        </div>
      </Container>

      <nav className={s.toc} aria-label="On this page">
        <Container className={s.tocInner}>
          <a href="#baselines">Against simple rules</a>
          <a href="#states">By state</a>
          <a href="#calibration">Honest confidence</a>
          <a href="#crops">Crop by crop</a>
          <a href="#years">Year to year</a>
          <a href="#drivers">What it looks at</a>
          <a href="#limits">Limits</a>
        </Container>
      </nav>

      <Section
        id="baselines"
        n="01"
        title="Better than the rules farmers already know"
        lead="The bar to beat is not zero. Most fields in the Corn Belt follow corn with soybean and soybean with corn, so a one-line rule already guesses two seasons in three."
        chart={<MethodChart />}
        notes={
          <>
            <Note title="How we tested">
              <p>
                Fields were split into {DATASET.folds} groups. The model trained on four and was scored on the fifth, then
                the groups rotated. No field was ever in training and test at once, so every score is for fields the
                model had never seen.
              </p>
            </Note>
            <Note title="Where the gap is largest">
              <p>
                Rare crops. The alternation rule can only say corn or soybean, so it never finds wheat, sorghum or
                alfalfa. Rare-crop quality: <strong>{model.macroF1.toFixed(2)}</strong> for the model against{" "}
                {alternation.macroF1.toFixed(2)}.
              </p>
            </Note>
          </>
        }
      />

      <Section
        id="states"
        n="02"
        title="Where rotations break the pattern, the model pulls ahead"
        lead="In Iowa and Illinois the rotation is nearly fixed, and the model matches the rule. Further west, wheat, sorghum and fallow enter the mix and the rule falls apart."
        chart={<StateChart />}
        notes={
          <>
            <Note title={`Kansas: ${pct(kansas.model, 0)} against ${pct(kansas.alternation, 0)}`}>
              <p>
                Almost twice as many right first picks as the alternation rule, on {kansas.rows.toLocaleString("en-US")}{" "}
                field-seasons.
              </p>
            </Note>
            <Note title="Said plainly" tone="info">
              <p>In the classic corn–soy belt the model is not smarter than the rotation. It earns its keep where the rotation is not a given.</p>
            </Note>
          </>
        }
      />

      <Section
        id="calibration"
        n="03"
        title="When it says 85%, it means 85%"
        lead="Each pick comes with a confidence. Before calibration the model was overconfident: picks made at 85% were right 73% of the time. One temperature setting, fitted on other fields, brought the two lines together."
        chart={<ReliabilityChart />}
        notes={
          <div className={s.compare}>
            <h3 className={s.compareTitle}>Before and after</h3>
            <table className={s.compareTable}>
              <thead>
                <tr>
                  <th scope="col">
                    <span className="visually-hidden">Measure</span>
                  </th>
                  <th scope="col">Before</th>
                  <th scope="col">After</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">Calibration error (ECE)</th>
                  <td>{CALIBRATION.before.ece.toFixed(3)}</td>
                  <td className={s.better}>{CALIBRATION.after.ece.toFixed(3)}</td>
                </tr>
                <tr>
                  <th scope="row">Log loss</th>
                  <td>{CALIBRATION.before.logLoss.toFixed(3)}</td>
                  <td className={s.better}>{CALIBRATION.after.logLoss.toFixed(3)}</td>
                </tr>
                <tr>
                  <th scope="row">Brier score</th>
                  <td>{CALIBRATION.before.brier.toFixed(3)}</td>
                  <td className={s.better}>{CALIBRATION.after.brier.toFixed(3)}</td>
                </tr>
              </tbody>
            </table>
            <p className={s.compareFoot}>
              Lower is better for all three. {CALIBRATION.method}, T = {CALIBRATION.temperature.toFixed(2)}. Calibration
              changes how sure the model sounds, not which crop it picks.
            </p>
          </div>
        }
      />

      <Section
        id="crops"
        n="04"
        title="Crop by crop"
        lead="Each row is the crop that really grew; each column is what the model picked first. The diagonal is how much of each crop it finds."
        chart={<ConfusionChart />}
        notes={
          <>
            <Note title="Training mix">
              <CropMix />
            </Note>
            <Note title={`Sorghum: ${pct(sorghum.recall, 0)} found`} tone="warning">
              <p>
                With only {sorghum.rows} field-seasons, sorghum is the weak spot. Its fields often look like corn or wheat
                to the model. A version that weights rare crops up finds 50% of sorghum, but loses a point on overall
                accuracy, so we kept the plain model.
              </p>
            </Note>
          </>
        }
      />

      <Section
        id="years"
        n="05"
        title="Steady from one season to the next"
        lead="A second test: train on six seasons, score on the seventh. The result holds between 77% and 83% in every year from 2019 to 2025."
        chart={<YearChart />}
        notes={
          <>
            <Note title="Across field groups">
              <ul className={s.folds}>
                {FOLDS.map((f) => (
                  <li key={f.fold}>
                    <span>Group {f.fold}</span>
                    <span className={s.foldTrack}>
                      <span style={{ width: `${f.top1 * 100}%` }} />
                    </span>
                    <span className={s.foldValue}>{pct(f.top1)}</span>
                  </li>
                ))}
              </ul>
            </Note>
            <Note title="Why this test reads higher" tone="info">
              <p>
                When a year is held out, the same fields still appear in other years, so the model knows them. The
                field-group test above is the stricter one, and it is the number we quote.
              </p>
            </Note>
          </>
        }
      />

      <Section
        id="drivers"
        n="06"
        title="What the model looks at"
        lead="Last year's crop carries the most weight by far, then the typical climate of the place, then the soil. Share of influence is the mean absolute SHAP value of each feature, as a part of the total."
        chart={<DriversChart />}
      />

      <Container as="section" id="limits" className={s.section} aria-labelledby="limits-title">
        <header className={s.sectionHead}>
          <span className={s.sectionNum} aria-hidden="true">
            07
          </span>
          <div>
            <h2 id="limits-title" className={s.sectionTitle}>
              What these numbers do not say
            </h2>
            <p className={s.sectionLead}>The model supports a decision. The farmer and the agronomist make it.</p>
          </div>
        </header>
        <div className={s.limitsGrid}>
          <ul className={s.limits}>
            {LIMITS.map((l) => (
              <li key={l}>
                <Icon name="warning" size={18} />
                <span>{l}</span>
              </li>
            ))}
          </ul>
          <div className={s.literature}>
            <span className={s.literatureValue}>{LITERATURE_CHECK.insideLimits}</span>
            <p>
              of real fields sit inside the textbook limits for soil acidity, clay, salinity, heat, rain and slope, across{" "}
              {LITERATURE_CHECK.crops} crops and {LITERATURE_CHECK.measures} measures. The crop-fit rules agree with what
              farmers really plant. These limits are still a draft, pending an agronomist's review.
            </p>
          </div>
        </div>
      </Container>

      <Container as="section" className={s.ctaWrap} aria-labelledby="cta-title">
        <div className={s.cta}>
          <h2 id="cta-title" className={s.ctaTitle}>
            See what the model says about your field.
          </h2>
          <ButtonLink to={ROUTES.pickField} variant="amber" size="lg">
            Pick your field
            <Icon name="arrow-right" />
          </ButtonLink>
        </div>
      </Container>
    </>
  );
}
