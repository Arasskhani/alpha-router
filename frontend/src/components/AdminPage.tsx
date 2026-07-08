import { ReactNode } from "react";
import { useReadOnly } from "../context/ReadOnlyContext";

type Props = {
  title: string;
  children: ReactNode;
  actions?: ReactNode;
};

/** Consistent admin page shell: fluid width, responsive typography. */
export default function AdminPage({ title, children, actions }: Props) {
  const readOnly = useReadOnly();

  return (
    <div className={`admin-page${readOnly ? " admin-page--read-only" : ""}`}>
      <header className="admin-page-header">
        <h1>{title}</h1>
        {actions ? <div className="admin-page-actions">{actions}</div> : null}
      </header>
      {children}
    </div>
  );
}
