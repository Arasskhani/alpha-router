/**
 * The page a person was on before Support, for a new ticket's technical
 * details ("the page I was on"). Shell reports every navigation; the Support
 * pages themselves are never kept. Only the path: no query string, which can
 * carry a search or a chat id.
 */
const SUPPORT_PREFIX = "/app/support";

let last = "";

export function rememberPage(path: string): void {
  if (path === SUPPORT_PREFIX || path.startsWith(`${SUPPORT_PREFIX}/`)) return;
  last = path;
}

export function pageBeforeSupport(): string {
  return last || window.location.pathname;
}
