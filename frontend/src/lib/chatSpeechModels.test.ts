import { describe, expect, it } from "vitest";
import {
  modelSupportsSpeech,
  modelSupportsTextToSpeech,
  resolveSpeechGenerationModel,
  resolveSpeechVoiceForModel,
} from "./chatSpeechModels";
import {
  buildSpeechRequestBody,
  shouldRouteToSpeechGeneration,
} from "./chatSpeech";

describe("chatSpeechModels", () => {
  it("uses catalog capability flags", () => {
    const m = {
      id: "model::1",
      name: "Provider speech",
      external_id: "openai/tts-1",
      supports_text_to_speech: true,
      is_speech_model: true,
    };
    expect(modelSupportsTextToSpeech(m)).toBe(true);
    expect(modelSupportsSpeech(m)).toBe(true);
  });

  it("resolves to concrete speech model", () => {
    const models = [
      { id: "model::chat", name: "Chat", external_id: "openai/gpt-4o" },
      {
        id: "model::speech",
        name: "TTS",
        external_id: "openai/tts-1",
        is_speech_model: true,
      },
    ];
    const resolved = resolveSpeechGenerationModel(models, models[0]);
    expect(resolved.id).toBe("model::speech");
  });

  it("remaps stale OpenAI voices onto catalog voices", () => {
    const m = {
      id: "model::speech",
      name: "Grok TTS",
      external_id: "x-ai/grok-voice-tts-1.0",
      supports_text_to_speech: true,
      supported_voices: ["eve", "ara", "rex"],
    };
    expect(resolveSpeechVoiceForModel(m, "alloy")).toBe("eve");
    expect(resolveSpeechVoiceForModel(m, "ara")).toBe("ara");
  });
});

describe("chatSpeech routing", () => {
  it("routes when tool and model support speech", () => {
    expect(
      shouldRouteToSpeechGeneration({
        speechGenerationEnabled: true,
        modelSupportsSpeech: true,
      }),
    ).toBe(true);
    expect(
      shouldRouteToSpeechGeneration({
        speechGenerationEnabled: false,
        modelSupportsSpeech: true,
      }),
    ).toBe(false);
  });

  it("builds speech request body", () => {
    const body = buildSpeechRequestBody({
      text: "Hello world",
      modelId: "openai/tts-1",
      sessionId: "s1",
      persist: true,
      voice: "alloy",
      format: "mp3",
      speed: 1.1,
    });
    expect(body.text).toBe("Hello world");
    expect(body.voice).toBe("alloy");
    expect(body.response_format).toBe("mp3");
    expect(body.speed).toBe(1.1);
    expect(body.chat_session_id).toBe("s1");
  });
});
