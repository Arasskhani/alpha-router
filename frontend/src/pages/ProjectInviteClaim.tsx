import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { formatApiError } from "../api";
import { claimInvitation } from "../lib/projectsApi";

export default function ProjectInviteClaimPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";
  const [status, setStatus] = useState<"loading" | "done" | "error">("loading");
  const [error, setError] = useState("");
  const [projectId, setProjectId] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setError("Missing invitation token.");
      return;
    }
    let active = true;
    claimInvitation(token)
      .then((project) => {
        if (!active) return;
        setProjectId(project.id);
        setStatus("done");
      })
      .catch((err) => {
        if (!active) return;
        setError(formatApiError(err));
        setStatus("error");
      });
    return () => {
      active = false;
    };
  }, [token]);

  if (status === "loading") {
    return <div className="admin-page"><div className="loading-state">Accepting invitation…</div></div>;
  }

  if (status === "done" && projectId) {
    return (
      <div className="admin-page">
        <div className="flash flash-success">You have joined the project.</div>
        <div className="dialog-actions">
          <button type="button" className="btn btn-primary" onClick={() => navigate(`/app/projects/${projectId}`)}>
            Open project
          </button>
          <Link to="/app/projects" className="btn btn-ghost">All projects</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <div className="flash flash-error">{error || "Invitation could not be accepted."}</div>
      <div className="dialog-actions">
        <Link to="/app/projects" className="btn btn-ghost">Back to projects</Link>
      </div>
    </div>
  );
}
