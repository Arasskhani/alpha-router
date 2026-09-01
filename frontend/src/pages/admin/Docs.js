import { jsx as _jsx } from "react/jsx-runtime";
import DocsShell, { buildDocNavGroups } from "../../components/DocsShell";
import { docSections } from "./docs/sections";
export default function Docs() {
    return (_jsx(DocsShell, { sidebarLabel: "Admin Guide", searchPlaceholder: "Search admin guide\u2026", sections: docSections, navGroups: buildDocNavGroups(docSections) }));
}
