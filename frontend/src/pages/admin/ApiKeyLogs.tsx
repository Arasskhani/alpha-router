import { useParams } from "react-router-dom";
import ApiLogs from "./ApiLogs";

export default function ApiKeyLogs() {
  const { keyId } = useParams();
  return <ApiLogs apiKeyId={Number(keyId)} />;
}
