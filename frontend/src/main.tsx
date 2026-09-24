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
import { checkForUpdate, startUpdateChecks } from "./lib/pwa/appUpdate";

applyThemeToDocument();
applyBlankFavicon();
// Before React renders: the browser's install event can fire before any component mounts.
startInstallListeners();
startInstallSuggestion();
startUpdateChecks();
// A page's code failed to load: often the app was upgraded while it stayed open,
// but a phone that is offline fails the same way. Ask the server whether its
// build changed before saying a new version is available. The error still
// reaches the route's error boundary, which offers a reload; nothing reloads by itself.
window.addEventListener("vite:preloadError", () => void checkForUpdate());
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
