import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { ConfirmProvider } from "./context/ConfirmContext";
import "./styles.css";
import "./generated/persianFonts.css";
import { migrateLegacyStorageKeys } from "./lib/session";
import { applyThemeToDocument } from "./lib/themeCache";
import { applyBlankFavicon } from "./lib/favicon";

migrateLegacyStorageKeys();
applyThemeToDocument();
applyBlankFavicon();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ConfirmProvider>
        <App />
      </ConfirmProvider>
    </BrowserRouter>
  </React.StrictMode>
);
