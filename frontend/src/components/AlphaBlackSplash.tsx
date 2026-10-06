import { useEffect, useState } from "react";

import { SPLASH_MS, SPLASH_TEXT } from "../lib/alphaBlackSplash";

/**
 * "AR455 was HERE", over the page for about two seconds, then gone. Decorative:
 * hidden from assistive technology and never in the way of a click. Each new
 * `run` plays it again.
 */
export default function AlphaBlackSplash({ run }: { run: number }) {
  const [doneRun, setDoneRun] = useState(0);
  useEffect(() => {
    if (run === 0) return;
    const timer = window.setTimeout(() => setDoneRun(run), SPLASH_MS);
    return () => window.clearTimeout(timer);
  }, [run]);

  if (run === 0 || doneRun === run) return null;
  return (
    <div key={run} className="alpha-black-splash" aria-hidden="true" data-testid="alpha-black-splash">
      <span className="alpha-black-splash__text">{SPLASH_TEXT}</span>
    </div>
  );
}
