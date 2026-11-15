import { HORIZONS, PRIORITIES, PRIORITY_LABEL, priorityText, yearsText } from "@/entities/analysis";
import { friendlyMessage } from "@/shared/api";
import { Button } from "@/shared/ui/button";
import { ChipToggle, SegmentedControl } from "@/shared/ui/choice";
import { Message } from "@/shared/ui/feedback";
import { TextField } from "@/shared/ui/form";
import { Icon } from "@/shared/ui/icon";
import { Panel, SectionTitle } from "@/shared/ui/layout";
import type { AnalysisSetupState } from "../model/setup";
import s from "./setup.module.css";

/** Analysis setup: priorities, crop history, horizon and optional local budget costs. */
export function AnalysisSetupSections({ setup }: { setup: AnalysisSetupState }) {
  return (
    <>
      <Panel as="section" aria-labelledby="setup-priorities">
        <SectionTitle id="setup-priorities">What matters most to you?</SectionTitle>
        <p className={s.muted}>Pick any that apply. If you pick none, the analysis is balanced.</p>
        <div className={s.chips}>
          {PRIORITIES.map((p) => (
            <ChipToggle key={p} pressed={setup.priorities.includes(p)} onToggle={() => setup.togglePriority(p)}>
              {PRIORITY_LABEL[p]}
            </ChipToggle>
          ))}
        </div>
      </Panel>

      <Panel as="section" aria-labelledby="setup-history">
        <SectionTitle id="setup-history">What grew here before?</SectionTitle>
        <p className={s.muted}>Filled in from satellite crop maps. Fix anything that is wrong.</p>
        <div className={s.history}>
          {setup.crops.map((row) => (
            <TextField
              key={row.year}
              label={String(row.year)}
              value={row.crop}
              maxLength={40}
              onChange={(e) => setup.setCrop(row.year, e.target.value)}
            />
          ))}
        </div>
      </Panel>

      <Panel as="section" aria-labelledby="setup-horizon">
        <SectionTitle id="setup-horizon">How far ahead?</SectionTitle>
        <SegmentedControl
          label="Years to look ahead"
          options={HORIZONS.map((n) => ({ value: n, label: yearsText(n) }))}
          value={setup.horizon}
          onChange={setup.setHorizon}
        />
        <p className={s.small}>3 years is a good start. Longer plans are less certain.</p>
      </Panel>

      <Panel as="section" aria-labelledby="setup-budget">
        <SectionTitle id="setup-budget">Rough budget</SectionTitle>
        <p className={s.muted}>Optional: use your own costs. Leave blank for public reference figures.</p>
        <div className={s.history}>
          <TextField label="Annual land cost ($/acre)" type="number" min="0" max="5000" step="0.01"
            value={setup.landRent} onChange={(e) => setup.setLandRent(e.target.value)} />
          <TextField label="Cover crop cost ($/acre per planting)" type="number" min="0" max="2000" step="0.01"
            value={setup.coverCost} onChange={(e) => setup.setCoverCost(e.target.value)} />
        </div>
        <p className={s.small}>
          Land cost: use 0 for no land charge. Cover cost includes seed, planting and termination.
          Enter only costs added beyond your normal crop program; leave blank if unknown.
          A rotation with cover crops needs this figure for a complete budget.
          {" "}<a href="https://finpack.umn.edu/news/new-cover-crops-report-and-climate-smart-ag-resources-2/">A 2025 farm study</a>
          {" "}reported $42/acre median direct cover expenses; that excludes some labor and ownership costs and is not a default quote.
        </p>
      </Panel>
    </>
  );
}

/** Aside panel: "Create analysis" and a summary of the choices. */
export function CreateAnalysisPanel({
  setup,
  disabled,
  onCreated,
}: {
  setup: AnalysisSetupState;
  disabled?: boolean;
  onCreated: (jobId: string) => void;
}) {
  const onClick = () => {
    setup.submit().then((job) => onCreated(job.job_id), () => undefined);
  };
  const pending = setup.create.isPending;
  return (
    <Panel>
      <Button variant="primary" size="lg" block onClick={onClick} disabled={disabled || pending}>
        {pending ? "Creating…" : "Create analysis"}
        {!pending && <Icon name="arrow-right" />}
      </Button>
      <p className={s.small}>
        Priorities: {priorityText(setup.priorities)}. Looking ahead {yearsText(setup.horizon)}.
      </p>
      {setup.create.isError && (
        <Message tone="error" role="alert">
          {friendlyMessage(setup.create.error)}
        </Message>
      )}
    </Panel>
  );
}
