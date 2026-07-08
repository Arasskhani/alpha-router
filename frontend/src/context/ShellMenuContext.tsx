import { createContext, useContext } from "react";

type ShellMenuContextValue = {
  openAdminMenu: () => void;
};

export const ShellMenuContext = createContext<ShellMenuContextValue | null>(null);

export function useShellMenu() {
  return useContext(ShellMenuContext);
}
