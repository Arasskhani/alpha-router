import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { ConfirmProvider } from "./context/ConfirmContext";
import "./styles.css";
import "./generated/persianFonts.css";
import { applyThemeToDocument } from "./lib/themeCache";
import { applyBlankFavicon } from "./lib/favicon";
import { onSessionReady } from "./api";
import { registerAppServiceWorker } from "./lib/pwa/registerServiceWorker";
import { startInstallListeners } from "./lib/pwa/installPrompt";
import { startInstallSuggestion } from "./lib/pwa/installSuggestion";
import { startUpdateChecks } from "./lib/pwa/appUpdate";

applyThemeToDocument();
applyBlankFavicon();
// Before React renders: the browser's install event can fire before any component mounts.
startInstallListeners();
startInstallSuggestion();
startUpdateChecks();
// Once signed in: the session carries the server's switch for the worker.
onSessionReady(() => registerAppServiceWorker());

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ConfirmProvider>
        <App />
      </ConfirmProvider>
    </BrowserRouter>
  </React.StrictMode>
);
