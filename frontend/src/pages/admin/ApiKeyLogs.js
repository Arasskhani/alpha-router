import { jsx as _jsx } from "react/jsx-runtime";
import { useParams } from "react-router-dom";
import ApiLogs from "./ApiLogs";
export default function ApiKeyLogs() {
    const { keyId } = useParams();
    return _jsx(ApiLogs, { apiKeyId: Number(keyId) });
}
