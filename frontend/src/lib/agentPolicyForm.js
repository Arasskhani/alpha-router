function asPolicyObject(value) {
    if (!value || typeof value !== "object" || Array.isArray(value))
        return {};
    return { ...value };
}
export function asStringList(value) {
    if (!Array.isArray(value))
        return [];
    const seen = new Set();
    const items = [];
    for (const entry of value) {
        const text = String(entry ?? "").trim();
        if (!text || seen.has(text))
            continue;
        seen.add(text);
        items.push(text);
    }
    return items;
}
export function splitKeywordInput(value) {
    return asStringList(value.split(/[,،\n]+/));
}
export function splitExampleInput(value) {
    return asStringList(value.split(/\r?\n/));
}
export function readPolicyForm(policies) {
    const model = asPolicyObject(policies.model_policy);
    const retrieval = asPolicyObject(policies.retrieval_policy);
    const routing = asPolicyObject(policies.routing_policy);
    const disclaimer = asPolicyObject(policies.disclaimer_policy);
    const localized = asPolicyObject(disclaimer.localized_text);
    return {
        primaryModelId: String(model.primary_model_id || ""),
        keywords: asStringList(routing.keywords),
        examples: asStringList(routing.examples),
        disclaimerEn: String(disclaimer.text || ""),
        disclaimerFa: String(localized.fa || ""),
        retrievalEnabled: retrieval.enabled !== false,
        requireEvidence: retrieval.require_evidence === true,
        citationsRequired: retrieval.citations_required !== false,
    };
}
export function applyPolicyForm(policies, form) {
    const model = asPolicyObject(policies.model_policy);
    const retrieval = asPolicyObject(policies.retrieval_policy);
    const routing = asPolicyObject(policies.routing_policy);
    const disclaimer = asPolicyObject(policies.disclaimer_policy);
    const localized = asPolicyObject(disclaimer.localized_text);
    const next = { ...policies };
    next.model_policy = {
        ...model,
        primary_model_id: form.primaryModelId.trim(),
    };
    next.retrieval_policy = {
        ...retrieval,
        enabled: form.retrievalEnabled,
        require_evidence: form.requireEvidence,
        citations_required: form.citationsRequired,
        ...(form.requireEvidence ? { fail_closed: true } : {}),
    };
    next.routing_policy = {
        ...routing,
        keywords: form.keywords,
        examples: form.examples,
    };
    const hasDisclaimer = Boolean(form.disclaimerEn.trim() || form.disclaimerFa.trim());
    next.disclaimer_policy = {
        ...disclaimer,
        text: form.disclaimerEn,
        localized_text: {
            ...localized,
            fa: form.disclaimerFa,
        },
        required: hasDisclaimer ? true : disclaimer.required === true,
    };
    return next;
}
export function policiesFromUnknown(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
        throw new Error("Every policy value must be a JSON object.");
    }
    const policies = {};
    for (const [key, policy] of Object.entries(value)) {
        if (!policy || typeof policy !== "object" || Array.isArray(policy)) {
            throw new Error("Every policy value must be a JSON object.");
        }
        policies[key] = { ...policy };
    }
    return policies;
}
