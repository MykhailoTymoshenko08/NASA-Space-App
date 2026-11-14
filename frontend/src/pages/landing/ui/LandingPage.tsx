import { useEffect } from "react";
import { ExploreMap } from "@/widgets/explore-map";
import { APP_NAME, ROUTES } from "@/shared/config";
import { ButtonLink } from "@/shared/ui/button";
import { Icon } from "@/shared/ui/icon";
import { Card, Container, Eyebrow } from "@/shared/ui/layout";
import s from "./landing.module.css";

const STEPS = [
  {
    n: "01",
    title: "Find your land",
    body: "Zoom from the country down to your county and pick a field. Or skip the map: choose a county, or paste a Google or Apple Maps link or coordinates. Field outlines cover Iowa, Illinois and Nebraska for now.",
  },
  {
    n: "02",
    title: "See base conditions",
    body: "We send the field's location to our server and bring back soil moisture, humidity, temperature, rain and soil data. Each value says if it was measured, modeled or estimated.",
  },
  {
    n: "03",
    title: "Get your analysis",
    body: "Create an analysis to compare crop rotations for the field, with the reasons behind each one. Read it on screen or export it to PDF.",
  },
] as const;

export function LandingPage() {
  useEffect(() => {
    document.title = `${APP_NAME}: know your field before you plant`;
  }, []);

  return (
    <>
      <Container as="section" className={s.hero} aria-labelledby="hero-title">
        <Eyebrow className={s.heroEyebrow}>Field data for U.S. farmers</Eyebrow>
        <h1 id="hero-title" className={s.heroTitle}>
          Know your field before you plant.
        </h1>
        <p className={s.heroLead}>
          Zoom from the whole country down to one estimated field area, or paste a map link or coordinates. We bring
          back soil moisture, humidity, temperature and soil data from NASA and USDA for that spot.
        </p>
        <div className={s.heroActions}>
          <ButtonLink to={ROUTES.pickField} variant="primary" size="lg">
            Pick your field
            <Icon name="arrow-right" />
          </ButtonLink>
          <a href="#map" className={s.textLink}>
            or explore the map below
          </a>
        </div>
      </Container>

      <Container as="section" id="map" aria-label="Field map">
        <ExploreMap />
      </Container>

      <Container as="section" id="how" className={s.how} aria-labelledby="how-title">
        <h2 id="how-title" className={s.sectionTitle}>
          From the whole country to one field in three steps
        </h2>
        <ol className={s.steps}>
          {STEPS.map((step) => (
            <Card as="li" key={step.n} className={s.step}>
              <div className={s.stepNumber} aria-hidden="true">
                {step.n}
              </div>
              <h3 className={s.stepTitle}>{step.title}</h3>
              <p className={s.muted}>{step.body}</p>
            </Card>
          ))}
        </ol>
      </Container>

      <Container as="section" className={s.ctaWrap} aria-labelledby="cta-title">
        <div className={s.cta}>
          <h2 id="cta-title" className={s.ctaTitle}>
            Start with the field you are about to plant.
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
