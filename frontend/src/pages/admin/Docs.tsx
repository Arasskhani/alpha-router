import DocsShell, { buildDocNavGroups } from "../../components/DocsShell";
import { docSections } from "./docs/sections";

export default function Docs() {
  return (
    <DocsShell
      sidebarLabel="Admin Guide"
      searchPlaceholder="Search admin guide…"
      sections={docSections}
      navGroups={buildDocNavGroups(docSections)}
    />
  );
}
