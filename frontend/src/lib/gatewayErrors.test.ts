import { describe, expect, it } from "vitest";
import { humanizeGatewayError } from "./gatewayErrors";

describe("humanizeGatewayError", () => {
  it("maps nginx 504 html to a short timeout message", () => {
    const raw = `<html><head><title>504 Gateway Time-out</title></head>
<body><center><h1>504 Gateway Time-out</h1></center><hr><center>nginx</center></body></html>`;
    expect(humanizeGatewayError(raw, 504)).toBe(
      "The request timed out at the gateway. Please retry.",
    );
  });

  it("maps nginx 413 html to an upload-limit message", () => {
    const raw = `<html><head><title>413 Request Entity Too Large</title></head>
<body><center><h1>413 Request Entity Too Large</h1></center><hr><center>nginx</center></body></html>`;
    expect(humanizeGatewayError(raw, 413)).toContain("too large");
  });

  it("leaves plain text alone", () => {
    expect(humanizeGatewayError("Attachments exceed the total per-message limit (36 MB).", 413)).toBe(
      "Attachments exceed the total per-message limit (36 MB).",
    );
  });
});
