"""Read each provider's own capability vocabulary, in its own words.

The classifier understood exactly one dialect: OpenRouter's
``architecture.input_modalities`` / ``output_modalities``. Every other
provider fell straight through to guessing a model's kind from its id, even
when the provider had published the answer in a different shape. Google says
``supportedGenerationMethods: ["embedContent"]``; Azure says
``capabilities: {"embeddings": true}``. Both are the provider telling us what
the model does, and both were being ignored.

So this module is the translation layer. It takes a provider type and the raw
catalog item stored in ``AIModel.pricing_raw`` and returns modality lists in
our own vocabulary, or ``None`` when the provider genuinely published nothing
usable — which is a real answer too, and the only case where the classifier is
allowed to fall back to the model's name.

Adding a provider means adding a reader here and nothing else.

A note on honesty: a reader only reports what the provider actually stated.
When a field is absent it stays absent rather than being defaulted, because
"the provider did not say" and "the provider said no" lead to different
behaviour downstream — the first permits a guess, the second forbids one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Our vocabulary. Anything a reader produces is normalised into these.
INPUT_TEXT = "text"
INPUT_IMAGE = "image"
INPUT_AUDIO = "audio"
INPUT_VIDEO = "video"

OUTPUT_TEXT = "text"
OUTPUT_IMAGE = "image"
OUTPUT_AUDIO = "audio"
OUTPUT_VIDEO = "video"
OUTPUT_EMBEDDINGS = "embeddings"
OUTPUT_RERANK = "rerank"
OUTPUT_SPEECH = "speech"
OUTPUT_TRANSCRIPTION = "transcription"


@dataclass(frozen=True)
class ProviderModalities:
    """What one provider said about one model."""

    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    #: Which reader produced this, for the operator-facing "why" and for tests.
    dialect: str = "unknown"

    def __bool__(self) -> bool:
        return bool(self.inputs or self.outputs)


@dataclass
class _Collected:
    inputs: set[str] = field(default_factory=set)
    outputs: set[str] = field(default_factory=set)


def _as_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip().lower() for item in value if str(item).strip()]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


# --------------------------------------------------------------------------
# Readers. Each returns None when this dialect is not present in the item.
# --------------------------------------------------------------------------


def _read_modality_lists(item: dict[str, Any]) -> ProviderModalities | None:
    """OpenRouter, and every gateway that copied its shape.

    ``architecture: {input_modalities: [...], output_modalities: [...]}``, or
    the same two keys at the top level.
    """
    arch = _dict(item.get("architecture")) or item
    inputs = _as_list(arch.get("input_modalities"))
    outputs = _as_list(arch.get("output_modalities"))
    if not inputs and not outputs:
        return None
    return ProviderModalities(inputs=tuple(inputs), outputs=tuple(outputs), dialect="modality_lists")


def _read_modalities_object(item: dict[str, Any]) -> ProviderModalities | None:
    """``modalities: {input: [...], output: [...]}`` — used by several
    OpenAI-compatible gateways."""
    modalities = _dict(item.get("modalities"))
    if not modalities:
        return None
    inputs = _as_list(modalities.get("input") or modalities.get("inputs"))
    outputs = _as_list(modalities.get("output") or modalities.get("outputs"))
    if not inputs and not outputs:
        return None
    return ProviderModalities(inputs=tuple(inputs), outputs=tuple(outputs), dialect="modalities_object")


#: Google's Gemini API lists the methods a model may be called with, which is
#: how it states capability. ``countTokens`` and friends say nothing about
#: modality and are deliberately absent.
_GOOGLE_METHOD_OUTPUTS: dict[str, str] = {
    "generatecontent": OUTPUT_TEXT,
    "streamgeneratecontent": OUTPUT_TEXT,
    "bidigeneratecontent": OUTPUT_TEXT,
    "embedcontent": OUTPUT_EMBEDDINGS,
    "batchembedcontents": OUTPUT_EMBEDDINGS,
    "embedtext": OUTPUT_EMBEDDINGS,
    "batchembedtext": OUTPUT_EMBEDDINGS,
    "generatemessage": OUTPUT_TEXT,
    "generatetext": OUTPUT_TEXT,
    "generateanswer": OUTPUT_TEXT,
}

#: Imagen and Veo are served through the prediction methods. Which of the two
#: it is comes from the method, not the model name: ``predictLongRunning`` is
#: the asynchronous job shape video generation uses.
_GOOGLE_PREDICT_METHODS = {"predict", "predictlongrunning"}


def _read_google_methods(item: dict[str, Any]) -> ProviderModalities | None:
    methods = _as_list(item.get("supportedGenerationMethods") or item.get("supported_generation_methods"))
    if not methods:
        return None
    collected = _Collected()
    known = False
    for method in methods:
        key = method.replace("_", "").replace("-", "")
        if key in _GOOGLE_METHOD_OUTPUTS:
            collected.outputs.add(_GOOGLE_METHOD_OUTPUTS[key])
            collected.inputs.add(INPUT_TEXT)
            known = True
        elif key in _GOOGLE_PREDICT_METHODS:
            # The method says "this is a prediction model" but not what it
            # emits. Leave the media kind to the rest of the pipeline rather
            # than inventing one; record only that text goes in.
            collected.inputs.add(INPUT_TEXT)
            known = True
    if not known:
        return None
    return ProviderModalities(
        inputs=tuple(sorted(collected.inputs)),
        outputs=tuple(sorted(collected.outputs)),
        dialect="google_generation_methods",
    )


#: Azure OpenAI's model list states capability as a map of booleans.
_AZURE_CAPABILITY_OUTPUTS: dict[str, str] = {
    "chat_completion": OUTPUT_TEXT,
    "completion": OUTPUT_TEXT,
    "embeddings": OUTPUT_EMBEDDINGS,
}


def _read_azure_capabilities(item: dict[str, Any]) -> ProviderModalities | None:
    capabilities = _dict(item.get("capabilities"))
    if not capabilities:
        return None
    collected = _Collected()
    known = False
    for key, value in capabilities.items():
        mapped = _AZURE_CAPABILITY_OUTPUTS.get(str(key).strip().lower())
        if mapped is None or not bool(value):
            continue
        collected.outputs.add(mapped)
        collected.inputs.add(INPUT_TEXT)
        known = True
    if not known:
        return None
    return ProviderModalities(
        inputs=tuple(sorted(collected.inputs)),
        outputs=tuple(sorted(collected.outputs)),
        dialect="azure_capabilities",
    )


#: Order matters only in that an explicit modality list is the most precise
#: statement a provider can make, so it is asked first. The rest are tried for
#: every provider: a gateway is free to speak any of these dialects, and a
#: reader that does not recognise its input returns None rather than guessing.
_READERS = (
    _read_modality_lists,
    _read_modalities_object,
    _read_google_methods,
    _read_azure_capabilities,
)


def provider_modalities(item: dict[str, Any] | None, *, provider_type: str | None = None) -> ProviderModalities | None:
    """Translate one provider catalog item, or None if it said nothing usable.

    ``provider_type`` is accepted for future readers that need to disambiguate
    identical shapes between providers; the current readers are keyed on the
    fields themselves, which is more robust than trusting a connection's
    configured type.
    """
    del provider_type
    if not isinstance(item, dict):
        return None
    for reader in _READERS:
        result = reader(item)
        if result:
            return result
    return None
