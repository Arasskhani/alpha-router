import { createContext, ReactNode, useCallback, useContext, useState } from "react";
import ConfirmModal from "../components/ConfirmModal";

export type ConfirmOptions = {
  title?: string;
  message: string;
  /** Exact message fragment to render with strong emphasis. */
  emphasize?: string;
  emphasizeDanger?: boolean;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Optional middle action (e.g. delete folder but keep chats). */
  secondaryLabel?: string;
  danger?: boolean;
};

export type PromptOptions = ConfirmOptions & {
  promptLabel: string;
  promptDefault?: string;
  promptRequired?: boolean;
  /** When set, Confirm stays disabled until the prompt exactly matches. */
  promptExactMatch?: string;
};

/** `true` = confirm, `false` = cancel, `"secondary"` = secondary when offered. */
export type ConfirmResult = boolean | "secondary";

type Pending =
  | (ConfirmOptions & { mode: "confirm"; resolve: (value: ConfirmResult) => void })
  | (PromptOptions & { mode: "prompt"; resolve: (value: string | null) => void });

type ConfirmContextValue = {
  confirm: (options: ConfirmOptions) => Promise<ConfirmResult>;
  /** Centered in-app prompt that replaces browser ``window.prompt``. */
  prompt: (options: PromptOptions) => Promise<string | null>;
};

const ConfirmContext = createContext<ConfirmContextValue | null>(null);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending | null>(null);

  const confirm = useCallback((options: ConfirmOptions) => {
    return new Promise<ConfirmResult>((resolve) => {
      setPending({ ...options, mode: "confirm", resolve });
    });
  }, []);

  const prompt = useCallback((options: PromptOptions) => {
    return new Promise<string | null>((resolve) => {
      setPending({
        ...options,
        mode: "prompt",
        promptRequired: options.promptRequired !== false,
        resolve,
      });
    });
  }, []);

  const finishConfirm = (result: ConfirmResult) => {
    if (pending?.mode === "confirm") pending.resolve(result);
    setPending(null);
  };

  const finishPrompt = (value: string | null) => {
    if (pending?.mode === "prompt") pending.resolve(value);
    setPending(null);
  };

  return (
    <ConfirmContext.Provider value={{ confirm, prompt }}>
      {children}
      <ConfirmModal
        open={pending !== null}
        title={pending?.title ?? (pending?.mode === "prompt" ? "Confirm" : "Confirm")}
        message={pending?.message ?? ""}
        emphasize={pending?.emphasize}
        emphasizeDanger={pending?.emphasizeDanger}
        confirmLabel={pending?.confirmLabel ?? (pending?.mode === "prompt" ? "Approve" : "Yes")}
        cancelLabel={pending?.cancelLabel ?? "Cancel"}
        secondaryLabel={pending?.mode === "confirm" ? pending.secondaryLabel : undefined}
        danger={pending?.danger}
        promptLabel={pending?.mode === "prompt" ? pending.promptLabel : undefined}
        promptDefault={pending?.mode === "prompt" ? pending.promptDefault : undefined}
        promptRequired={pending?.mode === "prompt" ? pending.promptRequired : undefined}
        promptExactMatch={pending?.mode === "prompt" ? pending.promptExactMatch : undefined}
        onConfirm={(promptValue) => {
          if (pending?.mode === "prompt") {
            finishPrompt(promptValue ?? "");
            return;
          }
          finishConfirm(true);
        }}
        onCancel={() => {
          if (pending?.mode === "prompt") {
            finishPrompt(null);
            return;
          }
          finishConfirm(false);
        }}
        onSecondary={
          pending?.mode === "confirm" && pending.secondaryLabel
            ? () => finishConfirm("secondary")
            : undefined
        }
      />
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): ConfirmContextValue {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm must be used within ConfirmProvider");
  return ctx;
}
