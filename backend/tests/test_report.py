"""PDF analysis report: GET /analyses/{job_id}/report.pdf and what the report prints."""

import re
import time

import pytest
import respx

from app.models import TimeSeries
from app.report.charts import chart, nice_step
from app.report.present import report_context
from app.report.render import ASSETS_URI, local_fetcher, report_html
from tests.contract import assert_matches_contract
from tests.report_sample import JOB_ID, sample_options, sample_result
from tests.test_analyses import F1, run
from tests.test_snapshots import mock_all

pytestmark = pytest.mark.contract


def text(html: str) -> str:
    """The visible text of the report HTML, whitespace collapsed (for content checks)."""
    body = re.sub(r"<(style|title)[^>]*>.*?</\1>", "", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


# ---------- endpoint ----------


def test_report_pdf_for_finished_job(client):
    _, done = run(client, {"selection": F1, "options": {"priorities": ["soil_health"], "horizon_years": 2}})
    job_id = done.json()["job_id"]
    r = client.get(f"/v1/analyses/{job_id}/report.pdf")
    assert r.status_code == 200, r.text
    assert_matches_contract(r)
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-") and b"%%EOF" in r.content[-64:]
    assert (
        r.headers["content-disposition"] == f'attachment; filename="seloai-analysis-polk-ia-{job_id[:8]}.pdf"'
    )
    # A finished job never changes: the second download is the same document, without rendering again.
    again = client.get(f"/v1/analyses/{job_id.upper()}/report.pdf")
    assert again.status_code == 200 and again.content == r.content


def test_report_uses_request_options(client):
    _, done = run(client, {"selection": F1, "options": {"priorities": ["soil_health", "erosion_control"]}})
    svc = client.app.state.services
    rec = svc.analyses.record(done.json()["job_id"])
    page = text(report_html(rec.job.result, rec.options, rec.job.job_id))
    assert "Priorities Soil health, Less erosion" in page
    assert "Looking ahead 3 years" in page


def test_report_not_ready_while_running(make_client, data_dir):
    c = make_client(data_dir, stub_duration_s=0.5)
    with respx.mock(assert_all_called=False) as router:
        mock_all(router)
        job_id = c.post("/v1/analyses", json={"selection": F1}).json()["job_id"]
        time.sleep(0.05)
        r = c.get(f"/v1/analyses/{job_id}/report.pdf")
        assert r.status_code == 409
        assert_matches_contract(r)
        err = r.json()["error"]
        assert err["code"] == "ANALYSIS_NOT_READY" and err["details"]["status"] in ("queued", "running")


def test_report_not_available_for_failed_job(make_client, data_dir):
    c = make_client(data_dir, stub_fail_rate=1.0)
    _, done = run(c, {"selection": F1})
    r = c.get(f"/v1/analyses/{done.json()['job_id']}/report.pdf")
    assert r.status_code == 409
    assert_matches_contract(r)
    assert r.json()["error"]["details"] == {"status": "failed"}
    assert "run it again" in r.json()["error"]["message"]


@pytest.mark.parametrize("job_id", ["7d3c5a2e-0000-4000-8000-000000000000", "not-a-uuid"])
def test_report_unknown_job_404(client, job_id):
    r = client.get(f"/v1/analyses/{job_id}/report.pdf")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


# ---------- content ----------


def test_summary_page():
    page = text(report_html(sample_result(), sample_options(), JOB_ID))
    assert "Estimated field area 80 acres (32.4 ha)" in page
    assert "County Polk County, IA" in page
    assert "Location 41.5868° N, 93.6250° W" in page
    assert "Latest mapped crops 2025 Corn · 2024 Soybeans · 2023 Corn" in page
    assert "Priorities Balanced" in page
    assert "Looking ahead 3 years" in page
    assert "Rotation analysis · Polk County, IA" in page
    assert "Estimated field area csb2025_190000123456 · Report 7c1e4a2b · Generated Nov 15, 2026" in page
    assert "Keep in mind" in page and "Crop history before 2023 is missing" in page


def test_strategies_sorted_with_baseline_deltas():
    ctx = report_context(sample_result(), sample_options(), JOB_ID)
    got = [(s.rank, s.score, s.delta) for s in ctx["strategies"]]
    assert got == [
        ("Best fit", 82, "+18 vs your current rotation"),
        ("Option 2", 77, "+13 vs your current rotation"),
        ("Option 3", 70, "+6 vs your current rotation"),
        ("Option 4", 64, "Baseline"),
    ]
    page = text(report_html(sample_result(), sample_options(), JOB_ID))
    assert "Your current rotation" in page and "Local review advised" in page
    assert "Confidence: Medium" in page
    assert "Season 3 Winter rye Cover crop" in page
    assert "Income index" in page  # criterion labels as on the web page


def test_conditions_in_us_units_with_sources():
    ctx = report_context(sample_result(), sample_options(), JOB_ID)
    groups = {g.title: {r.label: r for r in g.rows} for g in ctx["conditions"]}
    assert list(groups) == ["Moisture", "Weather", "Soil", "Land and plants"]
    temp = groups["Weather"]["Air temperature (30-day mean)"]
    assert (temp.value, temp.unit, temp.quality) == ("57", "°F", "Modeled")
    assert temp.detail == "Oct 13 to Nov 12, 2026 · NASA POWER, NASA · 50 km · Wider than this field"
    rain = groups["Weather"]["Rain, last 30 days"]
    assert (rain.value, rain.unit) == ("1.6", "in")
    assert (groups["Land and plants"]["Elevation"].value, groups["Land and plants"]["Elevation"].unit) == (
        "938",
        "ft",
    )
    som = groups["Soil"]["Soil organic matter"]
    assert som.detail == "gSSURGO, USDA NRCS · 30 m"  # a 30 m pixel is finer than the field: no warning
    assert groups["Soil"]["Soil texture"].unit == ""
    assert (
        groups["Soil"]["Soil nitrogen (total)"].note == "Estimated from organic matter. Not a soil lab test."
    )


def test_missing_metric_prints_not_available_with_reason():
    ctx = report_context(sample_result(), sample_options(), JOB_ID)
    ndvi = next(r for g in ctx["conditions"] for r in g.rows if r.label.startswith("Plant greenness"))
    assert (ndvi.value, ndvi.quality) == ("Not available", "Unavailable")
    assert ndvi.detail == "No cloud-free satellite pass in the last 14 days."


def test_entered_crop_history_and_buffered_point():
    base = sample_result()
    sel = base.selection.model_copy(
        update={
            "field_id": None,
            "resolved_by": "buffered_point",
            "boundary_type": "buffered_point",
            "buffer_m": 60,
        }
    )
    result = base.model_copy(update={"selection": sel})
    opts = sample_options(crop_history=[{"year": 2024, "crop": "Oats"}], horizon_years=1)
    page = text(report_html(result, opts, JOB_ID))
    assert "Crop history you entered 2024 Oats" in page
    assert "Circle around your point 80 acres" in page
    assert "Looking ahead 1 year " in page
    assert "Circle around your point 41.5868° N, 93.6250° W · Report" in page
    assert "Estimated field area" not in page


def test_unknown_options_and_empty_sections():
    result = sample_result(warnings=[], time_series=[], current_conditions=[])
    page = text(report_html(result, None, JOB_ID))
    assert "Priorities Not known" in page and "Looking ahead Not known" in page
    assert "Keep in mind" not in page
    assert "The last 6 months" not in page
    assert "No current conditions were available for this field." in page


def test_result_text_is_escaped():
    st = sample_result().strategies[0].model_copy(update={"name": '<img src="http://evil.test/x.png">Rye'})
    result = sample_result()
    result = result.model_copy(update={"strategies": [st, *result.strategies[1:]]})
    html = report_html(result, None, JOB_ID)
    assert '<img src="http://evil.test' not in html
    assert "&lt;img src=&#34;http://evil.test/x.png&#34;&gt;Rye" in html


@pytest.mark.parametrize(
    "url", ["http://evil.test/x.png", "file:///etc/passwd", f"{ASSETS_URI}/../render.py"]
)
def test_report_never_fetches_other_urls(url):
    with pytest.raises(ValueError):
        local_fetcher().fetch(url)


def test_report_fetches_bundled_assets():
    r = local_fetcher().fetch(f"{ASSETS_URI}/report.css")
    try:
        assert b"@page" in r.read()
    finally:
        r.close()


def test_pdf_layout_and_fonts():
    from weasyprint import HTML

    html = report_html(sample_result(), sample_options(), JOB_ID)
    doc = HTML(string=html, base_url=f"{ASSETS_URI}/", url_fetcher=local_fetcher()).render()
    # Summary, strategy cards (a long card breaks only between its blocks), conditions, data and disclaimer.
    assert 5 <= len(doc.pages) <= 7
    # Every glyph, chart labels included, comes from the bundled Open Sans: no system fallback font.
    doc.write_pdf()
    assert {f.family for f in doc.fonts.values()} == {"Open Sans"}


# ---------- ML wording ----------

ML_GAPS = [
    "If the field is irrigated, set irrigated=true \u2014 the recommendation will change",
    "Livestock / forage demand unknown",
    "No NDVI from Lina: the last-season stress rule is off",
]


def ml_result():
    """The sample with the ML service's own English text (ml_service/rotations.py, real.py)."""
    result = sample_result(
        warnings=[
            "No Landsat NDVI: bare soil in the timeline comes from the crop calendar "
            "and the last-season stress rule is off",
            "Field features were computed on the fly (SDA + POWER)",
            "Income is a relative 0-100 index, not a profit estimate.",
        ]
    )
    best = result.strategies[0].model_copy(
        update={
            "summary": "Sorghum instead of the thirstiest crops: better with heat and drought. "
            "Bare days 174->90 a year, erosion 0.6->0.4 t/ha, nitrogen -110->+0 kg/ha.",
            "evidence": [
                result.strategies[0]
                .evidence[0]
                .model_copy(
                    update={
                        "statement": "Erosion 0.6 -> 0.4 t/ha/yr (RUSLE: rain 650 mm/yr, K=0.05, slope 2.0%)"
                    }
                )
            ],
            "information_gaps": [*ML_GAPS, "Check with a local agronomist: Hybrid choice for your region"],
        }
    )
    rest = [
        s.model_copy(update={"information_gaps": [*ML_GAPS, "Income is a relative index, not money"]})
        for s in result.strategies[1:]
    ]
    return result.model_copy(update={"strategies": [best, *rest]})


def test_ml_wording_in_farmer_words():
    ctx = report_context(ml_result(), sample_options(), JOB_ID)
    best = ctx["best"]
    assert best.summary == "Sorghum instead of the thirstiest crops: better with heat and drought."
    assert best.evidence[0].statement == "Erosion 0.6 to 0.4 t/ha/yr"
    assert best.checks == ["Hybrid choice for your region"]
    # Gaps every strategy lists print once, with the warnings, merged by meaning and in farmer words.
    # ...and a card leaves out what "Keep in mind" already says (the income note, from a warning).
    assert [s.gaps for s in ctx["strategies"]] == [[], [], [], []]
    assert ctx["warnings"] == [
        "No recent satellite plant-health data, so last season's crop stress was not checked.",
        "Income is a score from 0 to 100 that compares options. It is not a profit estimate.",
        "We do not know if this field is irrigated. If it is, the advice would change.",
        "We do not know if you need hay or forage for livestock.",
    ]
    page = text(report_html(ml_result(), sample_options(), JOB_ID))
    for raw in ("->", "irrigated=true", "Lina", "RUSLE", "SDA + POWER", "Check with a local agronomist:"):
        assert raw not in page
    assert "Check with a local agronomist Hybrid choice for your region" in page


def test_unknown_ml_text_still_prints():
    result = sample_result(warnings=["A new model note -> keep it"])
    assert report_context(result, None, JOB_ID)["warnings"] == ["A new model note to keep it"]


def test_baseline_summary_in_farmer_words():
    from app.report.plain import summary

    raw = (
        "Baseline read from the CSB history 2020-2025 (cycle of 4 years, 100% match), continued for 3 years."
    )
    assert (
        summary(raw) == "Your rotation as mapped in 2020 to 2025 (a 4-year cycle), carried forward 3 years."
    )


def test_many_seasons_share_one_row():
    result = sample_result()
    seasons = [("Soybeans", "nitrogen_fixer"), ("Cereal rye", "cover_crop")] * 3
    rotation = [{"season_index": i, "crop": c, "role": r} for i, (c, r) in enumerate(seasons)]
    best = result.strategies[0].model_validate({**result.strategies[0].model_dump(), "rotation": rotation})
    html = report_html(result.model_copy(update={"strategies": [best, *result.strategies[1:]]}), None, JOB_ID)
    assert "seasons seasons-many" in html and "repeat(6, minmax(0, 1fr))" in html


def test_repeated_notes_and_datasets_print_once():
    result = sample_result()
    metrics = [m.model_copy(update={"note": "Same source note."}) for m in result.current_conditions[:3]]
    datasets = [
        *result.datasets_used,
        {"dataset": "SSURGO (Soil Survey Geographic Database) via Soil Data Access", "provider": "USDA NRCS"},
    ]
    result = sample_result(current_conditions=[m.model_dump() for m in metrics], datasets_used=datasets)
    ctx = report_context(result, None, JOB_ID)
    notes = [r.note for g in ctx["conditions"] for r in g.rows]
    assert notes == ["Same source note.", None, None]
    names = [d.dataset for d in ctx["datasets"]]
    assert sum("SSURGO" in n for n in names) == 1
    assert "SSURGO (Soil Survey Geographic Database) via Soil Data Access" in names


# ---------- charts ----------


def series(unit: str, values: list, key: str = "soil_moisture") -> TimeSeries:
    return TimeSeries.model_validate(
        {
            "key": key,
            "label": "Series",
            "unit": unit,
            "points": [
                {"t": f"2026-{5 + i // 4:02d}-{1 + 7 * (i % 4):02d}", "v": v} for i, v in enumerate(values)
            ],
        }
    )


def test_chart_line_breaks_at_gaps_and_reads_last_value():
    c = chart(series("m3/m3", [0.21, 0.25, None, 0.3, 0.28, None]))
    assert c.readout == "0.28 m³/m³" and c.when == "Jun 1"
    assert str(c.svg).count("<polyline") == 2  # never drawn through the gap
    assert 'font-family="Open Sans"' in str(c.svg)


def test_chart_rain_bars_in_inches():
    c = chart(series("mm", [0, 25.4, 50.8, 12.7], key="precip_weekly"))
    assert c.readout == "0.5 in" and c.when.startswith("Week of ")
    svg = str(c.svg)
    assert svg.count("<rect") == 4 and "<polyline" not in svg
    assert ">0</text>" in svg and ">2</text>" in svg  # axis from 0 to 2 in


def test_chart_without_values():
    c = chart(series("degC", [None, None]))
    assert c.readout == "Not available" and c.svg is None


@pytest.mark.parametrize(("span", "step"), [(0.14, 0.1), (1.6, 1), (3, 2), (36, 20), (0, 1)])
def test_nice_step(span, step):
    assert nice_step(span) == pytest.approx(step)
