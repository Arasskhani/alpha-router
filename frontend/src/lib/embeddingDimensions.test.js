import { describe, expect, it } from "vitest";
import { embeddingModelIdFromSpec, embeddingModelOptionLabel, suggestedEmbeddingDimensions, } from "./embeddingDimensions";
describe("suggestedEmbeddingDimensions", () => {
    it("maps common embedding models", () => {
        expect(suggestedEmbeddingDimensions("openai/text-embedding-3-large")).toBe(3072);
        expect(suggestedEmbeddingDimensions("text-embedding-3-small")).toBe(1536);
        expect(suggestedEmbeddingDimensions("text-embedding-ada-002")).toBe(1536);
        expect(suggestedEmbeddingDimensions("google/gemini-embedding-001")).toBe(3072);
        expect(suggestedEmbeddingDimensions("qwen3-embedding-8b")).toBe(4096);
        expect(suggestedEmbeddingDimensions("qwen3-embedding-4b")).toBe(2560);
        expect(suggestedEmbeddingDimensions("mistral-embed")).toBe(1024);
    });
    it("falls back to 1536", () => {
        expect(suggestedEmbeddingDimensions("unknown-embedder")).toBe(1536);
    });
    it("formats the option label with dimensions", () => {
        expect(embeddingModelOptionLabel("google/gemini-embedding-001", "openrouter")).toBe("google/gemini-embedding-001 · openrouter · 3072d");
    });
});
describe("embeddingModelIdFromSpec", () => {
    it("strips the provider prefix", () => {
        expect(embeddingModelIdFromSpec("openrouter:google/gemini-embedding-001")).toBe("google/gemini-embedding-001");
    });
});
