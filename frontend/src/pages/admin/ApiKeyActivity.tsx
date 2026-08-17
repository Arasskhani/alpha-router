import { useParams } from "react-router-dom";
import ActivityView from "../../components/activity/ActivityView";
import ApiKeyChangelog from "../../components/apiKeys/ApiKeyChangelog";
import ApiKeyInspectButtons from "../../components/apiKeys/ApiKeyInspectButtons";

export default function ApiKeyActivity() {
  const { keyId } = useParams();
  const id = Number(keyId);
  return (
    <ActivityView
      scope="api_key"
      apiKeyId={id}
      backLink={{ to: "/admin/api-keys", label: "API Keys" }}
      toolbarExtra={Number.isFinite(id) ? <ApiKeyInspectButtons keyId={id} active="activity" /> : null}
      footer={Number.isFinite(id) ? <ApiKeyChangelog keyId={id} /> : null}
    />
  );
}
