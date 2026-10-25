import { useState } from "react";
import { Link } from "react-router-dom";

import ResourceAccessEditor from "../admin/ResourceAccessEditor";
import { exchangeAdminApi } from "../../lib/exchangeMail";

/**
 * Exchange EWS › Access: who may connect a mailbox. It is the access list of
 * the `exchange_mail` chat tool, edited with the same editor and rules as
 * Chat Tools (public until restricted, a denial always wins).
 */
export default function ExchangeAccessTab({ canEdit }: { canEdit: boolean }) {
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  return (
    <div className="ews-admin-access">
      <p className="alert alert-info ews-admin-access__note" role="note">
        Only accounts that sign in with Active Directory can connect, whatever this list says.
      </p>
      <p className="muted-text">
        Public: every Active Directory account with an email address may connect. Private: only the people, groups,
        departments or roles allowed here. A denial always wins over an allow, and there is no exception for a Super
        Admin. The same list is the Exchange mail row on <Link to="/admin/chat-tools">Chat Tools</Link>; changes are
        recorded in Admin Logs.
      </p>
      {error ? (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="alert alert-success" role="status">
          {notice}
        </p>
      ) : null}
      <div className="ews-admin-access__editor">
        <ResourceAccessEditor
          title="Who may connect a mailbox"
          load={exchangeAdminApi.access}
          save={exchangeAdminApi.saveAccess}
          disabled={!canEdit}
          onError={(message) => {
            setNotice("");
            // The editor writes String(err): "Error: <the server's sentence>".
            setError(message.replace(/^Error:\s*/, ""));
          }}
          onSaved={() => {
            setError("");
            setNotice("Who may connect was saved.");
          }}
        />
      </div>
    </div>
  );
}
