import { useParams } from "react-router-dom";
import MediaLibrary from "../MediaLibrary";

export default function AdminUserMedia() {
  const { userId } = useParams();
  const id = Number(userId);
  if (!Number.isFinite(id)) {
    return <p className="alert alert-error">Invalid user id.</p>;
  }
  return (
    <MediaLibrary
      adminUserId={id}
      backLink={{ to: "/admin/users", label: "← Users" }}
    />
  );
}
