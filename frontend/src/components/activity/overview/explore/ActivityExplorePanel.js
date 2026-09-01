import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import ExploreChartCard from "./ExploreChartCard";
import ExploreTable from "./ExploreTable";
import ExploreToolbar from "./ExploreToolbar";
export default function ActivityExplorePanel({ explore, controls, hiddenGroups, onControlsChange, onDownloadPdf, }) {
    return (_jsxs("div", { className: "activity-explore", children: [_jsx(ExploreToolbar, { controls: controls, hiddenGroups: hiddenGroups, onChange: onControlsChange }), _jsx(ExploreChartCard, { explore: explore, controls: controls, onChange: onControlsChange, onDownloadPdf: onDownloadPdf }), _jsx(ExploreTable, { explore: explore })] }));
}
