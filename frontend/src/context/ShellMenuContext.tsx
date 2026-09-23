import { createContext, useContext } from "react";

type ShellMenuContextValue = {
  /** Show the application navigation (the chat page keeps it in a flyout). */
  openAdminMenu: () => void;
  /**
   * Phone layout: the page's side panel (chat history, or the navigation on
   * every other page) is a drawer that the topbar menu button opens. The
   * panel's owner reads `drawerOpen` and renders itself open or closed.
   */
  phone: boolean;
  drawerOpen: boolean;
  closeDrawer: () => void;
  /**
   * A page that renders its own drawer (the chat history) claims the menu
   * button while mounted; the returned function releases it. Unclaimed, the
   * button opens the navigation drawer, so it never does nothing.
   */
  claimDrawer: () => () => void;
};

export const ShellMenuContext = createContext<ShellMenuContextValue | null>(null);

export function useShellMenu() {
  return useContext(ShellMenuContext);
}
