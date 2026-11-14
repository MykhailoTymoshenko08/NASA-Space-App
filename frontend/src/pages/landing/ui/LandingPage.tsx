import { useEffect } from "react";
import { APP_NAME, ROUTES } from "@/shared/config";
import { ButtonLink } from "@/shared/ui/button";
import { Icon } from "@/shared/ui/icon";
import { Card, Container, Eyebrow } from "@/shared/ui/layout";
import s from "./landing.module.css";

const STEPS = [
  {
    n: "01",
    title: "Find your land",
    body: "Zoom from the country down to your county and pick a field. Or skip the map: type a county, paste a pin from Google or Apple Maps, or enter coordinates.",
  },
  {
    n: "02",
    title: "See base conditions",
    body: "We send the field's location to our server and bring back humidity, soil moisture, temperature and a nitrogen index built from NASA datasets.",
  },
  {
    n: "03",
    title: "Get your analysis",
    body: "Request an analysis and we send you a package of datasets our data science team selected for that field.",
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
          Zoom from the whole country down to one field, or drop in a map pin or coordinates. We bring back humidity,
          soil moisture and a nitrogen index from NASA datasets for that exact spot.
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

      <MapPlaceholder />

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

/**
 * Stage for the interactive map. The map itself waits for the backend's map API
 * (boundary + segment tiles). Until then this keeps the layout and offers the other way in.
 */
function MapPlaceholder() {
  return (
    <Container as="section" id="map" aria-labelledby="map-title">
      <div className={s.mapStage}>
        <div className={s.mapNotice}>
          <Icon name="layers" size={32} />
          <h2 id="map-title" className={s.mapTitle}>
            The field map is on its way
          </h2>
          <p className={s.muted}>
            Soon you will zoom from the whole country down to one field here. For now, pick your field by county, map
            pin or coordinates.
          </p>
          <ButtonLink to={ROUTES.pickField} variant="secondary" size="md">
            Pick a field
            <Icon name="arrow-right" />
          </ButtonLink>
        </div>
      </div>
    </Container>
  );
}
