import { useState } from "react";

import { BUILT_IN_PROMPTS, MAX_PROMPT_TEXT, promptError, type Prompt } from "./prompts";

type Props = {
  prompts: Prompt[];
  onSave: (prompts: Prompt[]) => Promise<void>;
  onClose: () => void;
};

/** The user's saved prompts: add, change and delete them. They stay in this browser. */
export default function PromptsView({ prompts, onSave, onClose }: Props) {
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState("");

  function edit(prompt: Prompt | null) {
    setEditing(prompt?.id ?? null);
    setName(prompt?.name ?? "");
    setText(prompt?.text ?? "");
    setError("");
  }

  async function save() {
    const cleanName = name.trim().toLowerCase();
    const problem = promptError(cleanName, text, prompts, editing);
    if (problem) {
      setError(problem);
      return;
    }
    const next = editing
      ? prompts.map((prompt) => (prompt.id === editing ? { ...prompt, name: cleanName, text } : prompt))
      : [...prompts, { id: crypto.randomUUID(), name: cleanName, text }];
    try {
      await onSave(next);
      edit(null);
    } catch {
      setError("The prompt could not be saved. Try again.");
    }
  }

  async function remove(id: string) {
    try {
      await onSave(prompts.filter((prompt) => prompt.id !== id));
      if (editing === id) edit(null);
    } catch {
      setError("The prompt could not be deleted. Try again.");
    }
  }

  return (
    <section className="prompts" aria-labelledby="prompts-title">
      <div className="prompts__head">
        <h2 id="prompts-title" className="prompts__title">
          Saved prompts
        </h2>
        <button type="button" className="btn btn--quiet" onClick={onClose}>
          Done
        </button>
      </div>
      <p className="prompts__hint">Type / at the start of a message to use one. They are kept in this browser only.</p>
      {prompts.length > 0 && (
        <ul className="prompts__list">
          {prompts.map((prompt) => (
            <li key={prompt.id} className="prompts__item">
              <span className="prompts__name">/{prompt.name}</span>
              <span className="prompts__text">{prompt.text}</span>
              <span className="prompts__actions">
                <button type="button" className="btn btn--quiet" aria-label={`Edit /${prompt.name}`} onClick={() => edit(prompt)}>
                  Edit
                </button>
                <button type="button" className="btn btn--quiet" aria-label={`Delete /${prompt.name}`} onClick={() => void remove(prompt.id)}>
                  Delete
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      <form
        className="prompts__form"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <label className="prompts__field">
          <span>Name</span>
          <input value={name} maxLength={32} placeholder="weekly-report" onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="prompts__field">
          <span>Text</span>
          <textarea value={text} rows={3} maxLength={MAX_PROMPT_TEXT} onChange={(event) => setText(event.target.value)} />
        </label>
        {error && (
          <p className="banner banner--error" role="alert">
            {error}
          </p>
        )}
        <div className="prompts__buttons">
          <button type="submit" className="btn btn--primary">
            {editing ? "Save changes" : "Add prompt"}
          </button>
          {editing && (
            <button type="button" className="btn btn--quiet" onClick={() => edit(null)}>
              Cancel
            </button>
          )}
        </div>
      </form>
      <p className="prompts__hint">Built in: {BUILT_IN_PROMPTS.map((prompt) => `/${prompt.name}`).join(", ")}</p>
    </section>
  );
}
