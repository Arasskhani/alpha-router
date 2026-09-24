import { useState } from "react";
import { useLocation } from "react-router-dom";

import { useSoftKeyboardOpen } from "../hooks/useSoftKeyboardOpen";
import { useUpdateAvailable } from "../lib/pwa/appUpdate";
import { promptInstall, useInstallState } from "../lib/pwa/installPrompt";
import {
  markInstallDone,
  shouldSuggest,
  snoozeSuggestion,
  suggestionInputFor,
} from "../lib/pwa/installSuggestion";
import InstallInstructionsModal from "./InstallInstructionsModal";

/**
 * A slim bar above the tab bar suggesting to install the app, once the user
 * has used it (lib/pwa/installSuggestion.ts has the rules). Part of the
 * layout, so it pushes the composer up instead of covering it. It is decided
 * on start-up and on a route change only, never while a reply is being read;
 * it steps aside while the keyboard is up, and while a dialog is open (CSS).
 */
export default function InstallBanner() {
  const path = useLocation().pathname.replace(/\/$/, "") || "/";
  const state = useInstallState();
  const keyboardOpen = useSoftKeyboardOpen();
  // The new-version notice takes the same place, and comes first.
  const updateAvailable = useUpdateAvailable();
  const [decidedFor, setDecidedFor] = useState<string | null>(null);
  const [wanted, setWanted] = useState(false);
  const [instructions, setInstructions] = useState(false);

  if (decidedFor !== path) {
    setDecidedFor(path);
    setWanted(shouldSuggest(suggestionInputFor(path, state)));
  }

  const offer = state === "can-prompt" || state === "ios-manual";
  const shown = wanted && offer && !keyboardOpen && !updateAvailable;

  const install = () => {
    setWanted(false);
    if (state === "ios-manual") {
      // iOS never says whether the app was added: showing how counts as the answer.
      snoozeSuggestion();
      setInstructions(true);
      return;
    }
    void promptInstall().then((outcome) => {
      if (outcome === "accepted") markInstallDone();
      else if (outcome === "dismissed") snoozeSuggestion();
    });
  };

  const notNow = () => {
    setWanted(false);
    snoozeSuggestion();
  };

  return (
    <>
      {shown ? (
        <div className="install-banner" role="region" aria-label="Install app">
          <img className="install-banner__mark" src="/icons/icon-192.png" alt="" width={26} height={26} />
          <span className="install-banner__text">Install Alpharouter as an app</span>
          <button type="button" className="install-banner__install" onClick={install}>
            {state === "ios-manual" ? "How to install" : "Install"}
          </button>
          <button type="button" className="install-banner__dismiss" onClick={notNow}>
            Not now
          </button>
        </div>
      ) : null}
      <InstallInstructionsModal open={instructions} onClose={() => setInstructions(false)} />
    </>
  );
}
