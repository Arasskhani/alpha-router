import { describe, expect, it } from "vitest";
import { modelSupportsTextToVideo, modelSupportsVideos, resolveVideoGenerationModel, } from "./chatVideoModels";
import { buildVideoRequestBody, shouldRouteToVideoGeneration } from "./chatVideo";
describe("chatVideoModels", () => {
    it("uses catalog capability flags", () => {
        const m = {
            id: "model::1",
            name: "Provider video",
            external_id: "provider/model",
            supports_text_to_video: true,
            is_video_model: true,
        };
        expect(modelSupportsTextToVideo(m)).toBe(true);
        expect(modelSupportsVideos(m)).toBe(true);
    });
    it("uses backend capability flags", () => {
        const m = {
            id: "model::2",
            name: "Custom",
            external_id: "vendor/custom",
            supports_text_to_video: true,
        };
        expect(modelSupportsVideos(m)).toBe(true);
    });
    it("resolves to concrete video model", () => {
        const models = [
            { id: "model::chat", name: "Chat", external_id: "openai/gpt-4o" },
            { id: "model::video", name: "Veo", external_id: "google/veo-3.1", is_video_model: true },
        ];
        const resolved = resolveVideoGenerationModel(models, models[0]);
        expect(resolved.id).toBe("model::video");
    });
});
describe("chatVideo routing", () => {
    it("routes when tool and model support video", () => {
        expect(shouldRouteToVideoGeneration({ videoGenerationEnabled: true, modelSupportsVideo: true })).toBe(true);
        expect(shouldRouteToVideoGeneration({ videoGenerationEnabled: false, modelSupportsVideo: true })).toBe(false);
    });
    it("builds img2vid when reference present", () => {
        const body = buildVideoRequestBody({
            prompt: "animate",
            model: "google/veo-3.1",
            chatSessionId: "s1",
            persist: true,
            referenceImage: "data:image/png;base64,aaa",
            duration: 30,
            resolution: "720p",
            aspectRatio: "16:9",
        });
        expect(body.operation).toBe("img2vid");
        expect(body.duration).toBe(30);
        expect(body.reference_image).toContain("data:image");
    });
});
