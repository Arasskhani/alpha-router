type Props = {
  serverUrl: string;
  waiting: boolean;
  message: string;
  onConnect: () => void;
  onCancel: () => void;
};

/** Not connected yet: one button, and what happens when it is pressed. */
export default function ConnectView({ serverUrl, waiting, message, onConnect, onCancel }: Props) {
  return (
    <main className="panel panel__center" aria-labelledby="connect-title">
      <h1 className="panel__title" id="connect-title">
        Connect to Alpharouter
      </h1>
      <p className="panel__server">{serverUrl}</p>
      {message && (
        <p className="banner banner--warning" role="status">
          {message}
        </p>
      )}
      {waiting ? (
        <>
          <p className="panel__text">
            A tab opened on Alpharouter. Sign in there if you are asked to, then choose Connect. This panel updates by
            itself.
          </p>
          <div className="panel__actions">
            <button type="button" className="btn" onClick={onConnect}>
              Open the page again
            </button>
            <button type="button" className="btn btn--quiet" onClick={onCancel}>
              Cancel
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="panel__text">
            Chat with your organization&apos;s models next to any page, and ask about the page you are on. You sign in
            with your Alpharouter account, in a normal tab.
          </p>
          <div className="panel__actions">
            <button type="button" className="btn btn--primary" onClick={onConnect}>
              Connect
            </button>
          </div>
        </>
      )}
    </main>
  );
}
