import { useLocation } from "react-router-dom";

export default function ReadOnlyBanner({ className = "" }: { className?: string }) {
  const path = useLocation().pathname;
  const adminReadOnly = path.startsWith("/admin");

  return (
    <div className={`readonly-account-banner alert alert-warning${className ? ` ${className}` : ""}`}>
      {adminReadOnly
        ? "Read-only administrator: you can browse admin pages and dashboards, but cannot create, edit, or delete anything."
        : "Your account is disabled (read-only). Browse your chat history here; use the profile menu for My Usage & Activity. You cannot send messages or use models."}
    </div>
  );
}
