import { describe, expect, it } from "vitest";
import { AUTO_AGENT_SELECTION, NO_AGENT_SELECTION } from "./agentChat";
import { copyFreshChatTools } from "./chatTools";
import { emptyProjectChatComposerPrefs, overlayComposerPrefsOnSession, } from "./projectChatComposer";
function session(overrides = {}) {
    return {
        id: "sess-1",
        title: "Shared thread",
        model: "gpt-text",
        messages: [],
        createdAt: 1,
        updatedAt: 1,
        ...overrides,
    };
}
describe("overlayComposerPrefsOnSession", () => {
    it("keeps tools off and Agent unset when this user has no prefs", () => {
        const shared = session({
            model: "image-specialist",
            toolsTouched: true,
            currentAgentId: "agent-from-other-user",
        });
        const next = overlayComposerPrefsOnSession(shared, null);
        expect(next.tools).toEqual(copyFreshChatTools());
        expect(next.toolsTouched).toBe(false);
        expect(next.selectedAgentSlug).toBeNull();
        expect(next.currentAgentId).toBeNull();
        expect(next.model).toBe("image-specialist");
    });
    it("applies this user's tools, model, and Agent without leaking a sticky Agent when none is selected", () => {
        const next = overlayComposerPrefsOnSession(session({ currentAgentId: "sticky-agent" }), {
            tools: { ...copyFreshChatTools(), webSearch: true },
            toolsTouched: true,
            model: "gpt-mine",
            selectedAgentSlug: "legal-consultant",
        });
        expect(next.tools.webSearch).toBe(true);
        expect(next.toolsTouched).toBe(true);
        expect(next.model).toBe("gpt-mine");
        expect(next.selectedAgentSlug).toBe("legal-consultant");
        expect(next.currentAgentId).toBe("sticky-agent");
    });
    it("treats none as no Agent even if the shared session still has a sticky binding", () => {
        const next = overlayComposerPrefsOnSession(session({ currentAgentId: "sticky-agent" }), {
            ...emptyProjectChatComposerPrefs(),
            selectedAgentSlug: NO_AGENT_SELECTION,
        });
        expect(next.selectedAgentSlug).toBeNull();
        expect(next.currentAgentId).toBeNull();
    });
    it("keeps auto Agent selection", () => {
        const next = overlayComposerPrefsOnSession(session(), {
            ...emptyProjectChatComposerPrefs(),
            selectedAgentSlug: AUTO_AGENT_SELECTION,
        });
        expect(next.selectedAgentSlug).toBe(AUTO_AGENT_SELECTION);
    });
});
