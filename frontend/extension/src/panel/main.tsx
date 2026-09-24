import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

function Panel() {
  return (
    <main>
      <h1>Alpharouter</h1>
      <p>Loading…</p>
    </main>
  );
}

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <Panel />
    </StrictMode>,
  );
}
