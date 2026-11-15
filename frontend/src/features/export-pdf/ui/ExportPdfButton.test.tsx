import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { attachmentName } from "@/entities/analysis";
import { env } from "@/shared/config";
import { renderRoutes } from "@/shared/lib/test";
import { ExportPdfButton } from "./ExportPdfButton";

const JOB = "7c1e4a2b-0000-4000-8000-000000000001";
const REPORT = `${env.apiBaseUrl}/analyses/${JOB}/report.pdf`;

const server = setupServer();
beforeAll(() => server.listen());
afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});
afterAll(() => server.close());

/** jsdom has no object URLs and never downloads: record what the button hands to the browser. */
function captureDownloads() {
  const saved: { name: string; href: string }[] = [];
  URL.createObjectURL = vi.fn(() => "blob:report");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    saved.push({ name: this.download, href: this.href });
  });
  return saved;
}

const render = () => renderRoutes([{ path: "/", element: <ExportPdfButton jobId={JOB} /> }], "/");

it("shows progress while the backend renders, then downloads the PDF under its server name", async () => {
  const saved = captureDownloads();
  server.use(
    http.get(REPORT, async () => {
      await delay(50);
      return new HttpResponse(new Uint8Array([37, 80, 68, 70]), {
        headers: {
          "Content-Type": "application/pdf",
          "Content-Disposition": 'attachment; filename="seloai-analysis-polk-ia-7c1e4a2b.pdf"',
        },
      });
    }),
  );
  render();
  await userEvent.click(screen.getByRole("button", { name: "Export to PDF" }));

  expect(screen.getByRole("button", { name: "Preparing your PDF..." })).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("Making your PDF report");

  expect(await screen.findByText(/Your PDF report is downloaded/)).toBeInTheDocument();
  expect(saved).toEqual([{ name: "seloai-analysis-polk-ia-7c1e4a2b.pdf", href: "blob:report" }]);
  const blob = vi.mocked(URL.createObjectURL).mock.calls[0]![0] as Blob;
  expect(blob.type).toBe("application/pdf");
  expect(screen.getByRole("button", { name: "Export to PDF" })).toBeEnabled();
});

it("explains a failure and lets the farmer try again", async () => {
  const saved = captureDownloads();
  let calls = 0;
  server.use(
    http.get(REPORT, () => {
      if (++calls === 1) {
        return HttpResponse.json(
          { error: { code: "ANALYSIS_NOT_READY", message: "The report is ready once the analysis has finished.",
            request_id: "r1", details: { status: "running" } } },
          { status: 409 },
        );
      }
      return new HttpResponse(new Uint8Array([37, 80, 68, 70]), { headers: { "Content-Type": "application/pdf" } });
    }),
  );
  render();
  await userEvent.click(screen.getByRole("button", { name: "Export to PDF" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("The report is ready once the analysis has finished.");
  expect(saved).toEqual([]);

  await userEvent.click(screen.getByRole("button", { name: "Try the PDF again" }));
  expect(await screen.findByText(/Your PDF report is downloaded/)).toBeInTheDocument();
  // No Content-Disposition: a readable fallback name.
  expect(saved).toEqual([{ name: "seloai-analysis-7c1e4a2b.pdf", href: "blob:report" }]);
});

it.each([
  ['attachment; filename="a b.pdf"', "a b.pdf"],
  ["attachment; filename*=UTF-8''O%27Brien.pdf", "O'Brien.pdf"],
  ["attachment", null],
  [null, null],
])("reads the file name from %s", (header, name) => {
  expect(attachmentName(header)).toBe(name);
});
