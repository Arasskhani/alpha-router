import { jsx as _jsx } from "react/jsx-runtime";
import { createContext, useContext } from "react";
const ReadOnlyContext = createContext(false);
export function ReadOnlyProvider({ value, children }) {
    return _jsx(ReadOnlyContext.Provider, { value: value, children: children });
}
export function useReadOnly() {
    return useContext(ReadOnlyContext);
}
