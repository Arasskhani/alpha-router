import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useNavigate } from "react-router-dom";
import { IconActivity, IconLogs } from "../icons/navIcons";
export default function ApiKeyInspectButtons({ keyId, active }) {
    const navigate = useNavigate();
    if (!Number.isFinite(keyId) || keyId <= 0)
        return null;
    return (_jsxs("div", { className: "api-key-inspect-btns", children: [_jsxs("button", { type: "button", className: `btn btn-sm btn-ghost api-key-inspect-btns__btn${active === "activity" ? " api-key-inspect-btns__btn--active" : ""}`, onClick: () => navigate(`/admin/api-keys/${keyId}/activity`), children: [_jsx(IconActivity, {}), "Activity"] }), _jsxs("button", { type: "button", className: `btn btn-sm btn-ghost api-key-inspect-btns__btn${active === "logs" ? " api-key-inspect-btns__btn--active" : ""}`, onClick: () => navigate(`/admin/api-keys/${keyId}/logs`), children: [_jsx(IconLogs, {}), "Logs"] })] }));
}
