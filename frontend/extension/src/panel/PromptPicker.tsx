import type { Prompt } from "./prompts";

type Props = {
  prompts: Prompt[];
  /** The row the arrow keys are on. */
  active: number;
  onPick: (prompt: Prompt) => void;
};

/** Quick prompts for what follows the slash; Enter or a click puts one in the composer. */
export default function PromptPicker({ prompts, active, onPick }: Props) {
  return (
    <div className="tab-picker" role="listbox" aria-label="Quick prompts">
      {prompts.length === 0 ? (
        <p className="tab-picker__note">No prompt by that name. Save your own from ⋯ → Saved prompts.</p>
      ) : (
        prompts.map((prompt, index) => (
          <button
            key={prompt.id}
            type="button"
            role="option"
            aria-selected={index === active}
            className={`tab-picker__item${index === active ? " tab-picker__item--active" : ""}`}
            // Keep the composer's focus.
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onPick(prompt)}
          >
            <span className="tab-picker__title">/{prompt.name}</span>
            <span className="tab-picker__site">{prompt.text}</span>
          </button>
        ))
      )}
    </div>
  );
}
