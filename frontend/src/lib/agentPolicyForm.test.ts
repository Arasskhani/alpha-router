import { describe, expect, it } from "vitest";
import {
  applyPolicyForm,
  policiesFromUnknown,
  readPolicyForm,
  splitExampleInput,
  splitKeywordInput,
} from "./agentPolicyForm";

const seeded = {
  model_policy: { primary_model_id: "openrouter/auto", temperature: 0.1 },
  retrieval_policy: {
    enabled: true,
    require_evidence: true,
    citations_required: true,
    fail_closed: true,
    final_limit: 8,
  },
  routing_policy: {
    enabled: true,
    keywords: ["vpn", "شبکه"],
    examples: ["How do I connect to the corporate VPN?"],
    priority: 10,
  },
  disclaimer_policy: {
    required: true,
    text: "Never share passwords.",
    localized_text: { fa: "رمز عبور را به اشتراک نگذارید." },
  },
  guardrail_policy: { fail_closed: true, hooks: ["pre_retrieval"] },
};

describe("agentPolicyForm", () => {
  it("reads operator-facing fields without dropping other policy keys", () => {
    const form = readPolicyForm(seeded);
    expect(form.primaryModelId).toBe("openrouter/auto");
    expect(form.keywords).toEqual(["vpn", "شبکه"]);
    expect(form.disclaimerFa).toContain("رمز عبور");
    expect(form.requireEvidence).toBe(true);
  });

  it("applies form edits while preserving advanced policy fields", () => {
    const next = applyPolicyForm(seeded, {
      ...readPolicyForm(seeded),
      keywords: ["vpn", "access"],
      primaryModelId: "vendor/model",
      requireEvidence: true,
    });
    expect(next.routing_policy.keywords).toEqual(["vpn", "access"]);
    expect(next.routing_policy.priority).toBe(10);
    expect(next.model_policy.temperature).toBe(0.1);
    expect(next.retrieval_policy.final_limit).toBe(8);
    expect(next.retrieval_policy.fail_closed).toBe(true);
    expect(next.guardrail_policy.hooks).toEqual(["pre_retrieval"]);
  });

  it("splits keyword and example input for non-JSON editing", () => {
    expect(splitKeywordInput("vpn, شبکه، password reset")).toEqual([
      "vpn",
      "شبکه",
      "password reset",
    ]);
    expect(splitExampleInput("How do I reset my password?\nبرای خطای ورود چه کار کنم؟")).toEqual([
      "How do I reset my password?",
      "برای خطای ورود چه کار کنم؟",
    ]);
  });

  it("rejects a policy document that is not a map of objects", () => {
    expect(() => policiesFromUnknown({ routing_policy: ["vpn"] })).toThrow(
      /JSON object/,
    );
  });
});
