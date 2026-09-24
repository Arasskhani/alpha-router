import Modal from "./Modal";

/**
 * How to add Alpharouter to the Home Screen on an iPhone or iPad, where no
 * button can do it for the user. A link opened from another app (Slack, Gmail)
 * may be in a Safari view without Add to Home Screen, hence the first line.
 */
export default function InstallInstructionsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} title="Install Alpharouter" onClose={onClose} panelClassName="install-instructions">
      <p className="install-instructions__lead">Open this page in Safari if you don't see these options.</p>
      <ol className="install-instructions__steps">
        <li>
          Tap <strong>Share</strong>. In Safari it may be under <strong>⋯</strong> next to the address bar; Chrome
          shows it in the address bar.
        </li>
        <li>
          Tap <strong>Add to Home Screen</strong>.
        </li>
        <li>
          Keep <strong>Open as Web App</strong> on, then tap <strong>Add</strong>.
        </li>
      </ol>
      <p className="install-instructions__note">Alpharouter then opens from its icon, full screen. Sign in once inside the app.</p>
      <div className="modal-actions">
        <button type="button" className="btn" onClick={onClose}>
          Got it
        </button>
      </div>
    </Modal>
  );
}
