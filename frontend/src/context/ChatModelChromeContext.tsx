import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

type ChatModelChromeSelection = {
  id: string;
  name: string;
  external_id?: string;
};

export type ChatModelChromeApi = {
  openReplacePicker: () => void;
  openAppendPicker: () => void;
  modelsReady: boolean;
  addModelDisabled: boolean;
  addModelTitle: string;
  addModelAriaLabel: string;
  selectedModels: ChatModelChromeSelection[];
  onRemoveModel: (id: string) => void;
};

type ChromeContextValue = {
  api: ChatModelChromeApi | null;
  register: (next: ChatModelChromeApi | null) => void;
};

const ChatModelChromeContext = createContext<ChromeContextValue | null>(null);

export function ChatModelChromeProvider({ children }: { children: ReactNode }) {
  const [api, setApi] = useState<ChatModelChromeApi | null>(null);
  const register = useCallback((next: ChatModelChromeApi | null) => {
    setApi(next);
  }, []);
  const value = useMemo(() => ({ api, register }), [api, register]);
  return <ChatModelChromeContext.Provider value={value}>{children}</ChatModelChromeContext.Provider>;
}

export function useChatModelChromeRegister() {
  const ctx = useContext(ChatModelChromeContext);
  if (!ctx) {
    throw new Error("useChatModelChromeRegister requires ChatModelChromeProvider");
  }
  return ctx.register;
}

export function useChatModelChromeApi() {
  return useContext(ChatModelChromeContext)?.api ?? null;
}
