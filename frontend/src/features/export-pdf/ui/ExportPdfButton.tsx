import { useState } from "react";
import { Button } from "@/shared/ui/button";
import { Message } from "@/shared/ui/feedback";
import { Icon } from "@/shared/ui/icon";

/**
 * Export to PDF is the only export (no zip, no per-dataset downloads).
 * The contract has no PDF endpoint (design README, open question 3), so this prints the result page
 * with print styles; the browser's print dialog saves it as PDF.
 */
export function ExportPdfButton() {
  const [started, setStarted] = useState(false);
  const onClick = () => {
    setStarted(true);
    // Let the status render before the blocking print dialog opens.
    setTimeout(() => window.print(), 50);
  };
  return (
    <>
      <Button variant="primary" size="lg" block onClick={onClick}>
        <Icon name="file" />
        Export to PDF
      </Button>
      {started && (
        <Message tone="info" role="status">
          Choose "Save as PDF" in the print window. The PDF has everything you see on this page.
        </Message>
      )}
    </>
  );
}
