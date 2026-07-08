import { FormEvent, useEffect, useState } from "react";
import Modal from "../Modal";

export type ConnectionFormValues = {
  name: string;
  provider_type: string;
  api_key: string;
  base_url: string;
  sync_interval_hours: number;
};

type Props = {
  open: boolean;
  title: string;
  initial?: Partial<ConnectionFormValues> & { api_key_masked?: string };
  onClose: () => void;
  onSubmit: (values: ConnectionFormValues) => Promise<void>;
};

const BASE_URL_HINTS: Record<string, string> = {
  openrouter: "https://openrouter.ai/api/v1",
  openai: "https://api.openai.com/v1",
  anthropic: "https://api.anthropic.com/v1",
  google: "https://generativelanguage.googleapis.com/v1beta",
};

const defaultValues: ConnectionFormValues = {
  name: "",
  provider_type: "",
  api_key: "",
  base_url: "",
  sync_interval_hours: 6,
};

export default function ConnectionFormModal({ open, title, initial, onClose, onSubmit }: Props) {
  const [form, setForm] = useState<ConnectionFormValues>(defaultValues);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open) return;
    setErr("");
    setForm({
      name: initial?.name ?? "",
      provider_type: initial?.provider_type ?? "",
      api_key: "",
      base_url: initial?.base_url ?? "",
      sync_interval_hours: initial?.sync_interval_hours ?? 6,
    });
  }, [open, initial]);

  const baseHint =
    BASE_URL_HINTS[form.provider_type.trim().toLowerCase()] ||
    "e.g. https://api.example.com/v1";

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) {
      setErr("Name is required.");
      return;
    }
    if (!form.provider_type.trim()) {
      setErr("Provider is required.");
      return;
    }
    if (!initial && !form.api_key.trim()) {
      setErr("API key is required.");
      return;
    }
    setSaving(true);
    setErr("");
    try {
      await onSubmit({
        ...form,
        name: form.name.trim(),
        provider_type: form.provider_type.trim().toLowerCase(),
        base_url: form.base_url.trim(),
        api_key: form.api_key.trim(),
      });
      onClose();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} title={title} onClose={onClose}>
      <form className="connection-form" onSubmit={handleSubmit}>
        <label className="connection-form__label">
          Name
          <input
            className="input-block"
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            required
          />
        </label>
        <label className="connection-form__label">
          Provider
          <input
            className="input-block"
            value={form.provider_type}
            onChange={(e) => setForm((f) => ({ ...f, provider_type: e.target.value }))}
            placeholder="Type provider (e.g. openrouter, openai, custom)"
            required
          />
        </label>
        <label className="connection-form__label">
          Base URL
          <input
            className="input-block mono"
            value={form.base_url}
            onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))}
            placeholder={baseHint}
          />
          <span className="muted-text connection-form__hint">
            Enter the API root for this use case (chat, embeddings, video, etc.). Sync uses this URL for model
            discovery. Leave empty to use the provider default.
          </span>
        </label>
        <label className="connection-form__label">
          API key
          {initial?.api_key_masked ? (
            <span className="muted-text connection-form__hint">Current: {initial.api_key_masked}</span>
          ) : null}
          <input
            type="password"
            className="input-block"
            value={form.api_key}
            onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))}
            placeholder={initial ? "Leave blank to keep current key" : "Provider API key"}
            autoComplete="off"
            required={!initial}
          />
        </label>
        <label className="connection-form__label">
          Sync schedule (hours between auto-sync)
          <input
            type="number"
            min={0}
            className="input-block"
            value={form.sync_interval_hours}
            onChange={(e) => setForm((f) => ({ ...f, sync_interval_hours: Number(e.target.value) }))}
          />
          <span className="muted-text connection-form__hint">0 = manual sync only (Sync now in the table)</span>
        </label>
        {err && <p className="alert alert-error">{err}</p>}
        <div className="dialog-actions">
          <button type="submit" className="btn" disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
          <button type="button" className="btn btn-ghost dialog-actions-cancel" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}
