import { describe, expect, it } from "vitest";
import { AUTO_AGENT_SELECTION, NO_AGENT_SELECTION, agentCompletionMetadataFromSse, agentRequestFields, buildCitationNumbering, citationDisplayMarker, formatAgentAnswerForDisplay, nextAgentSelection, resolveAgentSelection, } from "./agentChat";
describe("agentRequestFields", () => {
    it("explicitly opts out of Agent routing when no Agent is enabled", () => {
        expect(agentRequestFields(NO_AGENT_SELECTION)).toEqual({ agent_auto_route: false });
        expect(agentRequestFields("")).toEqual({ agent_auto_route: false });
    });
    it("builds an auto-routing request", () => {
        expect(agentRequestFields(AUTO_AGENT_SELECTION)).toEqual({
            agent_auto_route: true,
            include_citations: true,
        });
    });
    it("builds an explicit Agent request", () => {
        expect(agentRequestFields("legal-consultant")).toEqual({
            agent_slug: "legal-consultant",
            agent_auto_route: false,
            include_citations: true,
        });
    });
});
describe("nextAgentSelection", () => {
    it("starts from no Agent and enables the picked one", () => {
        expect(nextAgentSelection(NO_AGENT_SELECTION, "it-helpdesk")).toBe("it-helpdesk");
    });
    it("disables the Agent when the active one is picked again", () => {
        expect(nextAgentSelection("it-helpdesk", "it-helpdesk")).toBe(NO_AGENT_SELECTION);
    });
    it("keeps a single Agent enabled when switching", () => {
        expect(nextAgentSelection("it-helpdesk", "hr-assistant")).toBe("hr-assistant");
    });
});
describe("resolveAgentSelection", () => {
    it("starts a fresh chat without an Agent", () => {
        expect(resolveAgentSelection(undefined, undefined)).toBe(NO_AGENT_SELECTION);
    });
    it("keeps the Agent bound by earlier turns of the same chat", () => {
        expect(resolveAgentSelection(undefined, "finance-consultant")).toBe("finance-consultant");
    });
    it("lets an explicit switch-off win over the bound Agent", () => {
        expect(resolveAgentSelection(null, "finance-consultant")).toBe(NO_AGENT_SELECTION);
    });
    it("prefers the Agent chosen in this chat", () => {
        expect(resolveAgentSelection("hr-assistant", "finance-consultant")).toBe("hr-assistant");
    });
});
describe("agentCompletionMetadataFromSse", () => {
    it("normalizes Agent metadata and keeps only citation objects with ids", () => {
        expect(agentCompletionMetadataFromSse({
            agent_run_id: "run-1",
            agent_id: "agent-1",
            agent_version_id: "version-1",
            agent_name: "Legal Consultant",
            agent_status: "succeeded",
            routing_outcome: "explicit",
            completion_reason_code: "verified",
            citations: [
                { citation_id: "cite-1", title: "Policy" },
                { title: "Missing id" },
                null,
            ],
        })).toEqual({
            agentRunId: "run-1",
            agentId: "agent-1",
            agentVersionId: "version-1",
            agentName: "Legal Consultant",
            agentStatus: "succeeded",
            routingOutcome: "explicit",
            completionReasonCode: "verified",
            citations: [{ citation_id: "cite-1", title: "Policy" }],
        });
    });
});
describe("formatAgentAnswerForDisplay", () => {
    it("replaces long cite markers with short isolated numbers", () => {
        const citations = [
            { citation_id: "14e1fc73-da1e-5fa9-9662-f58c3e49e7ca", title: "AD" },
            { citation_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", title: "Tier" },
        ];
        const formatted = formatAgentAnswerForDisplay("حساب Administrator را ایمن کنید [[cite:14e1fc73-da1e-5fa9-9662-f58c3e49e7ca]]. سپس Tiering [[cite:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb]].", citations);
        expect(formatted).toContain("\u2068[1]\u2069");
        expect(formatted).toContain("\u2068[2]\u2069");
        expect(formatted).not.toContain("[[cite:");
        expect(citationDisplayMarker(citations[0], 0)).toBe("[1]");
        expect(buildCitationNumbering(citations).get(citations[1].citation_id)).toBe(2);
    });
});
