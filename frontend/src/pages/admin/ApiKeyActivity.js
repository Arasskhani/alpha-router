import { jsx as _jsx } from "react/jsx-runtime";
import { useParams } from "react-router-dom";
import ActivityView from "../../components/activity/ActivityView";
import ApiKeyChangelog from "../../components/apiKeys/ApiKeyChangelog";
import ApiKeyInspectButtons from "../../components/apiKeys/ApiKeyInspectButtons";
export default function ApiKeyActivity() {
    const { keyId } = useParams();
    const id = Number(keyId);
    return (_jsx(ActivityView, { scope: "api_key", apiKeyId: id, backLink: { to: "/admin/api-keys", label: "API Keys" }, toolbarExtra: Number.isFinite(id) ? _jsx(ApiKeyInspectButtons, { keyId: id, active: "activity" }) : null, footer: Number.isFinite(id) ? _jsx(ApiKeyChangelog, { keyId: id }) : null }));
}
