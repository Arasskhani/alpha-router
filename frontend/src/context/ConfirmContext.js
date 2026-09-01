import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { createContext, useCallback, useContext, useState } from "react";
import ConfirmModal from "../components/ConfirmModal";
const ConfirmContext = createContext(null);
export function ConfirmProvider({ children }) {
    const [pending, setPending] = useState(null);
    const confirm = useCallback((options) => {
        return new Promise((resolve) => {
            setPending({ ...options, mode: "confirm", resolve });
        });
    }, []);
    const prompt = useCallback((options) => {
        return new Promise((resolve) => {
            setPending({
                ...options,
                mode: "prompt",
                promptRequired: options.promptRequired !== false,
                resolve,
            });
        });
    }, []);
    const finishConfirm = (result) => {
        if (pending?.mode === "confirm")
            pending.resolve(result);
        setPending(null);
    };
    const finishPrompt = (value) => {
        if (pending?.mode === "prompt")
            pending.resolve(value);
        setPending(null);
    };
    return (_jsxs(ConfirmContext.Provider, { value: { confirm, prompt }, children: [children, _jsx(ConfirmModal, { open: pending !== null, title: pending?.title ?? (pending?.mode === "prompt" ? "Confirm" : "Confirm"), message: pending?.message ?? "", emphasize: pending?.emphasize, emphasizeDanger: pending?.emphasizeDanger, confirmLabel: pending?.confirmLabel ?? (pending?.mode === "prompt" ? "Approve" : "Yes"), cancelLabel: pending?.cancelLabel ?? "Cancel", secondaryLabel: pending?.mode === "confirm" ? pending.secondaryLabel : undefined, danger: pending?.danger, promptLabel: pending?.mode === "prompt" ? pending.promptLabel : undefined, promptDefault: pending?.mode === "prompt" ? pending.promptDefault : undefined, promptRequired: pending?.mode === "prompt" ? pending.promptRequired : undefined, promptExactMatch: pending?.mode === "prompt" ? pending.promptExactMatch : undefined, onConfirm: (promptValue) => {
                    if (pending?.mode === "prompt") {
                        finishPrompt(promptValue ?? "");
                        return;
                    }
                    finishConfirm(true);
                }, onCancel: () => {
                    if (pending?.mode === "prompt") {
                        finishPrompt(null);
                        return;
                    }
                    finishConfirm(false);
                }, onSecondary: pending?.mode === "confirm" && pending.secondaryLabel
                    ? () => finishConfirm("secondary")
                    : undefined })] }));
}
export function useConfirm() {
    const ctx = useContext(ConfirmContext);
    if (!ctx)
        throw new Error("useConfirm must be used within ConfirmProvider");
    return ctx;
}
