import { jsx as _jsx } from "react/jsx-runtime";
import { createContext, useCallback, useContext, useMemo, useState } from "react";
const ChatModelChromeContext = createContext(null);
export function ChatModelChromeProvider({ children }) {
    const [api, setApi] = useState(null);
    const register = useCallback((next) => {
        setApi(next);
    }, []);
    const value = useMemo(() => ({ api, register }), [api, register]);
    return _jsx(ChatModelChromeContext.Provider, { value: value, children: children });
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
