import { useNavigate } from "react-router-dom";
import { IconActivity, IconLogs } from "../icons/navIcons";

type Props = {
  keyId: number;
  active?: "activity" | "logs";
};

export default function ApiKeyInspectButtons({ keyId, active }: Props) {
  const navigate = useNavigate();
  if (!Number.isFinite(keyId) || keyId <= 0) return null;
  return (
    <div className="api-key-inspect-btns">
      <button
        type="button"
        className={`btn btn-sm btn-ghost api-key-inspect-btns__btn${active === "activity" ? " api-key-inspect-btns__btn--active" : ""}`}
        onClick={() => navigate(`/admin/api-keys/${keyId}/activity`)}
      >
        <IconActivity />
        Activity
      </button>
      <button
        type="button"
        className={`btn btn-sm btn-ghost api-key-inspect-btns__btn${active === "logs" ? " api-key-inspect-btns__btn--active" : ""}`}
        onClick={() => navigate(`/admin/api-keys/${keyId}/logs`)}
      >
        <IconLogs />
        Logs
      </button>
    </div>
  );
}
