import { useParams } from "react-router-dom";
import ActivityView from "../../components/activity/ActivityView";
import ApiKeyChangelog from "../../components/apiKeys/ApiKeyChangelog";

export default function ApiKeyActivity() {
  const { keyId } = useParams();
  const id = Number(keyId);
  return (
    <ActivityView
      scope="api_key"
      apiKeyId={id}
      backLink={{ to: "/admin/api-keys", label: "API Keys" }}
      footer={Number.isFinite(id) ? <ApiKeyChangelog keyId={id} /> : null}
    />
  );
}
