import { type FormEvent, type KeyboardEvent, useEffect, useId, useMemo, useRef, useState } from "react";

import Modal from "../Modal";
import { searchKeyWarning, WEB_SEARCH_PROVIDERS, webSearchProvider, type WebSearchProviderId } from "../../lib/webSearchProviders";

export type WebSearchConnectionValues = {
  name: string;
  provider_type: WebSearchProviderId;
  api_key: string;
  base_url: string;
  engine_id: string;
  priority: number;
  price_per_request_usd: number;
};

export type WebSearchTestResult =
  | { ok: true; count: number; elapsed_ms: number; results: { title: string; url: string }[] }
  | { ok: false; elapsed_ms: number; error: { code: string; message: string } };

type Props = {
  open: boolean;
  title: string;
  /** Editing a saved connection: its values, and the masked key it has. */
  initial?: Partial<WebSearchConnectionValues> & { api_key_masked?: string };
  onClose: () => void;
  onSubmit: (values: WebSearchConnectionValues) => Promise<void>;
  /** One real search with what the form holds (a saved connection's stored key when none is typed). */
  onTest: (values: WebSearchConnectionValues) => Promise<WebSearchTestResult>;
};

const EMPTY: WebSearchConnectionValues = {
  name: WEB_SEARCH_PROVIDERS[0].label,
  provider_type: "brave",
  api_key: "",
  base_url: "",
  engine_id: "",
  priority: 100,
  price_per_request_usd: WEB_SEARCH_PROVIDERS[0].suggestedPrice,
};

/**
 * The form for a web search connection: only search services to choose from, a key field
 * that says it is a Web Search API key, the fields the chosen service needs, and a Test.
 */
export default function WebSearchConnectionModal({ open, title, initial, onClose, onSubmit, onTest }: Props) {
  // Mounted afresh for each opening (the panel renders it only while open), so it starts from its props.
  const [form, setForm] = useState<WebSearchConnectionValues>(() => ({ ...EMPTY, ...initial, api_key: "" }));
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [err, setErr] = useState("");
  const [test, setTest] = useState<WebSearchTestResult | null>(null);
  const editing = Boolean(initial);
  // The service is picked like a model provider: a search box whose suggestions narrow as you type.
  const [serviceQuery, setServiceQuery] = useState<string | null>(null);
  const [serviceOpen, setServiceOpen] = useState(false);
  const [activeService, setActiveService] = useState(0);
  const serviceWrapRef = useRef<HTMLDivElement>(null);
  const serviceListboxId = useId();
  // A stored key belongs to its service: moved to another one, the connection needs that service's own key.
  const keepsKey = editing && form.provider_type === initial?.provider_type;

  const provider = webSearchProvider(form.provider_type) ?? WEB_SEARCH_PROVIDERS[0];
  const keyWarning = searchKeyWarning(provider.id, form.api_key);

  function chooseProvider(id: WebSearchProviderId) {
    const next = webSearchProvider(id) ?? WEB_SEARCH_PROVIDERS[0];
    setTest(null);
    setForm((f) => ({
      ...f,
      provider_type: next.id,
      // A new connection starts at the service's usual price; an edited one keeps what was set.
      price_per_request_usd: editing ? f.price_per_request_usd : next.suggestedPrice,
      name: !f.name.trim() || WEB_SEARCH_PROVIDERS.some((p) => p.label === f.name) ? next.label : f.name,
    }));
  }

  const serviceSuggestions = useMemo(() => {
    const q = (serviceQuery ?? "").trim().toLowerCase();
    if (!q) return [...WEB_SEARCH_PROVIDERS];
    return WEB_SEARCH_PROVIDERS.filter(
      (p) => p.label.toLowerCase().includes(q) || p.id.includes(q) || p.blurb.toLowerCase().includes(q),
    );
  }, [serviceQuery]);

  useEffect(() => {
    if (!serviceOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (serviceWrapRef.current && !serviceWrapRef.current.contains(e.target as Node)) closeServices();
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [serviceOpen]);

  /** Closing the list puts the chosen service's name back in the box: only a listed service can be chosen. */
  function closeServices() {
    setServiceOpen(false);
    setServiceQuery(null);
    setActiveService(0);
  }

  function pickService(id: WebSearchProviderId) {
    chooseProvider(id);
    closeServices();
  }

  function onServiceKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      if (serviceOpen) {
        // Escape closes the list first; the dialog closes on the next one.
        e.preventDefault();
        e.stopPropagation();
      }
      closeServices();
      return;
    }
    if (!serviceOpen) {
      if (e.key === "ArrowDown") setServiceOpen(true);
      return;
    }
    if (serviceSuggestions.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveService((i) => (i + 1) % serviceSuggestions.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveService((i) => (i - 1 + serviceSuggestions.length) % serviceSuggestions.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      pickService((serviceSuggestions[activeService] ?? serviceSuggestions[0]).id);
    }
  }

  function problem(): string {
    if (!form.name.trim()) return "Name is required.";
    if (provider.needsKey && !keepsKey && !form.api_key.trim()) return `${provider.label} needs its Web Search API key.`;
    if (provider.needsBaseUrl && !form.base_url.trim()) return "Enter the address of your SearXNG server.";
    if (provider.needsEngineId && !form.engine_id.trim()) return "Enter the search engine id (cx) of your Programmable Search Engine.";
    if (!Number.isInteger(form.priority) || form.priority < 1 || form.priority > 1000) return "Priority must be a whole number from 1 to 1000.";
    if (!Number.isFinite(form.price_per_request_usd) || form.price_per_request_usd < 0 || form.price_per_request_usd > 10) {
      return "The price of one search must be between 0 and 10 USD.";
    }
    return "";
  }

  function cleaned(): WebSearchConnectionValues {
    return { ...form, name: form.name.trim(), api_key: form.api_key.trim(), base_url: form.base_url.trim(), engine_id: form.engine_id.trim() };
  }

  async function runTest() {
    const issue = problem();
    if (issue && !issue.startsWith("Name")) {
      setErr(issue);
      return;
    }
    setErr("");
    setTesting(true);
    try {
      setTest(await onTest(cleaned()));
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setTesting(false);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const issue = problem();
    if (issue) {
      setErr(issue);
      return;
    }
    setSaving(true);
    setErr("");
    try {
      await onSubmit(cleaned());
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
        <p className="muted-text connection-form__hint">
          A <strong>web search</strong> connection: its key is sent only to the search service, for the chat&apos;s Web
          Search. Model providers (OpenAI, OpenRouter…) are added in the Model providers tab.
        </p>
        <label className="connection-form__label">
          Search service
          <div className="connection-provider-combobox" ref={serviceWrapRef}>
            <input
              className="input-block"
              value={serviceQuery ?? provider.label}
              onChange={(e) => {
                setServiceQuery(e.target.value);
                setServiceOpen(true);
                setActiveService(0);
              }}
              onFocus={(e) => {
                setServiceOpen(true);
                e.currentTarget.select();
              }}
              onKeyDown={onServiceKeyDown}
              placeholder="Type or pick a search service (e.g. brave, tavily)"
              autoComplete="off"
              aria-autocomplete="list"
              aria-expanded={serviceOpen}
              aria-controls={serviceListboxId}
              role="combobox"
              data-testid="web-search-service"
            />
            {serviceOpen ? (
              <div className="connection-provider-combobox__panel card" role="listbox" id={serviceListboxId}>
                {serviceSuggestions.length ? (
                  <ul className="connection-provider-combobox__list">
                    {serviceSuggestions.map((p, index) => (
                      <li key={p.id}>
                        <button
                          type="button"
                          role="option"
                          aria-selected={p.id === form.provider_type}
                          data-service={p.id}
                          className={`connection-provider-combobox__item${
                            index === activeService ? " connection-provider-combobox__item--active" : ""
                          }`}
                          onMouseDown={(e) => e.preventDefault()}
                          onClick={() => pickService(p.id)}
                        >
                          <span className="connection-provider-combobox__label">{p.label}</span>
                          <span className="connection-provider-combobox__meta">
                            <code>{p.id}</code>
                            <span className="muted-text">{p.blurb}</span>
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted-text connection-provider-combobox__empty">No search service matches.</p>
                )}
              </div>
            ) : null}
          </div>
          <span className="muted-text connection-form__hint">{provider.blurb}</span>
        </label>
        <label className="connection-form__label">
          Name
          <input className="input-block" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} required />
        </label>
        {provider.needsKey ? (
          <label className="connection-form__label">
            Web Search API key
            {keepsKey && initial?.api_key_masked ? <span className="muted-text connection-form__hint">Current: {initial.api_key_masked}</span> : null}
            <input
              type="password"
              className="input-block"
              value={form.api_key}
              onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))}
              placeholder={keepsKey ? "Leave blank to keep the current key" : `${provider.label} API key`}
              autoComplete="off"
              aria-describedby={keyWarning ? "web-search-key-warning" : undefined}
            />
            {keyWarning ? (
              <span id="web-search-key-warning" className="alert alert-warning connection-form__hint" role="status">
                {keyWarning}
              </span>
            ) : null}
          </label>
        ) : null}
        {provider.needsBaseUrl ? (
          <label className="connection-form__label">
            SearXNG address
            <input
              className="input-block mono"
              value={form.base_url}
              onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))}
              placeholder="https://search.example.org"
            />
            <span className="muted-text connection-form__hint">
              JSON results must be on in its settings.yml (search → formats: json). A private address needs
              ALLOW_SSRF_PRIVATE_RANGES=true on this server.
            </span>
          </label>
        ) : null}
        {provider.needsEngineId ? (
          <label className="connection-form__label">
            Search engine id (cx)
            <input
              className="input-block mono"
              value={form.engine_id}
              onChange={(e) => setForm((f) => ({ ...f, engine_id: e.target.value }))}
              placeholder="e.g. 0123456789abcdef0"
            />
          </label>
        ) : null}
        <div className="web-search-numbers">
          <label className="connection-form__label">
            Priority
            <input
              type="number"
              min={1}
              max={1000}
              step={1}
              className="input-block"
              value={form.priority}
              onChange={(e) => setForm((f) => ({ ...f, priority: Number(e.target.value) }))}
            />
            <span className="muted-text connection-form__hint">Lower is asked first; the next is asked when one fails.</span>
          </label>
          <label className="connection-form__label">
            Price per search (USD)
            <input
              type="number"
              min={0}
              max={10}
              step={0.0001}
              className="input-block"
              value={form.price_per_request_usd}
              onChange={(e) => setForm((f) => ({ ...f, price_per_request_usd: Number(e.target.value) }))}
            />
            <span className="muted-text connection-form__hint">Charged to the person&apos;s budget for each search.</span>
          </label>
        </div>
        {test ? (
          test.ok ? (
            <p className="alert alert-success" role="status">
              The search worked: {test.count} result{test.count === 1 ? "" : "s"} in {test.elapsed_ms} ms
              {test.results[0] ? ` — first: ${test.results[0].title}` : ""}.
            </p>
          ) : (
            <p className="alert alert-error" role="status">
              The search failed ({test.error.code}): {test.error.message}
            </p>
          )
        ) : null}
        {err && <p className="alert alert-error" role="alert">{err}</p>}
        <div className="dialog-actions">
          <button type="submit" className="btn" disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => void runTest()} disabled={testing}>
            {testing ? "Testing…" : "Test"}
          </button>
          <button type="button" className="btn btn-ghost dialog-actions-cancel" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}
