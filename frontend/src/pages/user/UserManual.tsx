import DocsShell, { buildDocNavGroups } from "../../components/DocsShell";
import { userManualSections } from "./docs/sections";
export default function UserManual() {
  return (
    <DocsShell
      sidebarLabel="User Manual"
      searchPlaceholder="Search manual…"
      sections={userManualSections}
      navGroups={buildDocNavGroups(userManualSections)}
    />
  );
}
