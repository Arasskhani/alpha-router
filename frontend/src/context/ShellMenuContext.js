import { createContext, useContext } from "react";
export const ShellMenuContext = createContext(null);
export function useShellMenu() {
    return useContext(ShellMenuContext);
}
