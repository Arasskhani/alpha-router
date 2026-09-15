import { describe, expect, it } from "vitest";
import { errorCodeLabel, operationTypeLabel } from "./requestLogCostDetails";

describe("operationTypeLabel", () => {
  it("names the kinds the API Logs Type column shows", () => {
    expect(operationTypeLabel("video")).toBe("Video");
    expect(operationTypeLabel("chat")).toBe("Chat");
    expect(operationTypeLabel("transcription")).toBe("Transcription");
  });

  it("passes an unknown kind through rather than hiding it", () => {
    expect(operationTypeLabel("rerank")).toBe("Rerank");
    expect(operationTypeLabel("something_new")).toBe("Something_new");
  });

  it("shows a dash when the row predates the usage ledger", () => {
    expect(operationTypeLabel(null)).toBe("—");
    expect(operationTypeLabel("")).toBe("—");
  });
});

describe("errorCodeLabel", () => {
  it("turns the stored code into something an operator reads", () => {
    expect(errorCodeLabel("timeout")).toBe("Timed out");
    expect(errorCodeLabel("connect_error")).toBe("Could not connect");
    expect(errorCodeLabel("http_client_error")).toBe("Rejected by provider");
  });

  it("degrades readably for a code it does not know", () => {
    expect(errorCodeLabel("some_new_code")).toBe("some new code");
    expect(errorCodeLabel(null)).toBe("");
  });
});
