import { createContext, ReactNode, useCallback, useContext, useState } from "react";
import ConfirmModal from "../components/ConfirmModal";

export type ConfirmOptions = {
  title?: string;
  message: string;
  /** Exact message fragment to render with strong emphasis. */
  emphasize?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Optional middle action (e.g. delete folder but keep chats). */
  secondaryLabel?: string;
  danger?: boolean;
};

/** `true` = confirm, `false` = cancel, `"secondary"` = secondary when offered. */
export type ConfirmResult = boolean | "secondary";

type Pending = ConfirmOptions & { resolve: (value: ConfirmResult) => void };

type ConfirmContextValue = {
  confirm: (options: ConfirmOptions) => Promise<ConfirmResult>;
};

const ConfirmContext = createContext<ConfirmContextValue | null>(null);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending | null>(null);

  const confirm = useCallback((options: ConfirmOptions) => {
    return new Promise<ConfirmResult>((resolve) => {
      setPending({ ...options, resolve });
    });
  }, []);

  const finish = (result: ConfirmResult) => {
    pending?.resolve(result);
    setPending(null);
  };

  return (
    <ConfirmContext.Provider value={{ confirm }}>
      {children}
      <ConfirmModal
        open={pending !== null}
        title={pending?.title ?? "Confirm"}
        message={pending?.message ?? ""}
        emphasize={pending?.emphasize}
        confirmLabel={pending?.confirmLabel ?? "Yes"}
        cancelLabel={pending?.cancelLabel ?? "No"}
        secondaryLabel={pending?.secondaryLabel}
        danger={pending?.danger}
        onConfirm={() => finish(true)}
        onCancel={() => finish(false)}
        onSecondary={pending?.secondaryLabel ? () => finish("secondary") : undefined}
      />
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): ConfirmContextValue {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm must be used within ConfirmProvider");
  return ctx;
}
