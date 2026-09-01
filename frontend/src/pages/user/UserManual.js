import { jsx as _jsx } from "react/jsx-runtime";
import DocsShell, { buildDocNavGroups } from "../../components/DocsShell";
import { userManualSections } from "./docs/sections";
export default function UserManual() {
    return (_jsx(DocsShell, { sidebarLabel: "User Manual", searchPlaceholder: "Search manual\u2026", sections: userManualSections, navGroups: buildDocNavGroups(userManualSections) }));
}
