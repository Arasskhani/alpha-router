import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import ModelProviderIcon from "./ModelProviderIcon";
/**
 * Model label with a colored provider brand mark on the left.
 */
export default function ModelName({ modelId, label, provider, size = 16, className = "", showIcon = true, }) {
    const text = (label || modelId || "").trim() || "—";
    return (_jsxs("span", { className: `model-name${className ? ` ${className}` : ""}`, children: [showIcon ? (_jsx(ModelProviderIcon, { modelId: modelId || label, provider: provider, size: size })) : null, _jsx("span", { className: "model-name__text", children: text })] }));
}
