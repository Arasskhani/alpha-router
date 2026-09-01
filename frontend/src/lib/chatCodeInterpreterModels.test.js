import { describe, expect, it } from "vitest";
import { codeInterpreterBlockedReason, filterCodeInterpreterModels, findCodeInterpreterFallbackModel, isVerifiedCodeInterpreterModel, modelSupportsCodeInterpreter, resolveCodeInterpreterModel, } from "./chatCodeInterpreterModels";
function model(id, external_id, compat) {
    return {
        id,
        name: id,
        external_id,
        code_interpreter: compat
            ? {
                status: "unknown",
                compatible: false,
                selectable: true,
                ...compat,
            }
            : undefined,
    };
}
describe("Code Interpreter model compatibility", () => {
    it("keeps models without compatibility data usable", () => {
        expect(modelSupportsCodeInterpreter(model("a", "vendor/new"))).toBe(true);
    });
    it("keeps unknown models usable so new releases are not lost", () => {
        const unknown = model("a", "vendor/new", { status: "unknown", selectable: true });
        expect(modelSupportsCodeInterpreter(unknown)).toBe(true);
        expect(isVerifiedCodeInterpreterModel(unknown)).toBe(false);
    });
    it("hides models the backend marked blocked or quarantined", () => {
        const blocked = model("b", "vendor/bad", {
            status: "incompatible",
            selectable: false,
            reason_detail: "Returns malformed tool calls.",
        });
        const quarantined = model("c", "vendor/flaky", {
            status: "degraded",
            selectable: false,
        });
        expect(modelSupportsCodeInterpreter(blocked)).toBe(false);
        expect(modelSupportsCodeInterpreter(quarantined)).toBe(false);
        expect(codeInterpreterBlockedReason(blocked)).toBe("Returns malformed tool calls.");
        expect(codeInterpreterBlockedReason(quarantined)).toBeTruthy();
    });
    it("filters the picker list without model-name heuristics", () => {
        const models = [
            model("good", "vendor/good", { status: "compatible", compatible: true, selectable: true }),
            model("bad", "vendor/bad", { status: "incompatible", selectable: false }),
            model("new", "vendor/new"),
        ];
        expect(filterCodeInterpreterModels(models).map((m) => m.id)).toEqual([
            "good",
            "new",
        ]);
    });
    it("prefers a verified model, then Auto Router, then any allowed model", () => {
        const verified = model("verified", "vendor/good", {
            status: "compatible",
            compatible: true,
            selectable: true,
        });
        const auto = model("auto", "openrouter/auto");
        const plain = model("plain", "vendor/new");
        expect(findCodeInterpreterFallbackModel([auto, plain, verified])?.id).toBe("verified");
        expect(findCodeInterpreterFallbackModel([plain, auto])?.id).toBe("auto");
        expect(findCodeInterpreterFallbackModel([plain])?.id).toBe("plain");
    });
    it("keeps the user's model unless it is blocked", () => {
        const blocked = model("bad", "vendor/bad", {
            status: "incompatible",
            selectable: false,
        });
        const allowed = model("ok", "vendor/new");
        expect(resolveCodeInterpreterModel([blocked, allowed], allowed)?.id).toBe("ok");
        expect(resolveCodeInterpreterModel([blocked, allowed], blocked)?.id).toBe("ok");
        expect(resolveCodeInterpreterModel([blocked], blocked)?.id).toBe("bad");
    });
});
