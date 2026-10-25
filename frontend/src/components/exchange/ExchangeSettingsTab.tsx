import { useEffect, useMemo, useState } from "react";

import SearchableModelSelect from "../admin/SearchableModelSelect";
import { useConfirm } from "../../context/ConfirmContext";
import { CheckField, Field, FieldError, NumberField, Switch, describedBy, errorText } from "./ExchangeControls";
import ExchangeTestPanel from "./ExchangeTestPanel";
import {
  MailApiError,
  SETTING_BOUNDS,
  exchangeAdminApi,
  type CatalogModel,
  type ExchangeSettings,
  type ExchangeSettingsResponse,
} from "../../lib/exchangeMail";
import {
  EWS_URL_EXAMPLE,
  LOGIN_FORMAT_OPTIONS,
  ONLY_SUPER_ADMIN_TEXT,
  PASSWORDS_RESET_TEXT,
  countCertificates,
  exampleLogin,
  fieldForServerMessage,
  resetsPasswords,
  validateExchangeSettings,
  type SettingsErrors,
  type SettingsField,
} from "../../lib/exchangeAdmin";

type Props = {
  data: ExchangeSettingsResponse | null;
  /** Why the settings could not be read; with "Try again". */
  loadError?: string;
  onRetry?: () => void;
  /** Read-only administrators read the same page with every control disabled. */
  canEdit: boolean;
  /**
   * Where passwords are sent (EWS and Autodiscover addresses, certificate checks) is a Super Admin's decision:
   * other writers see those four controls disabled, with a note.
   */
  canEditEndpoint: boolean;
  onSaved: (next: ExchangeSettingsResponse) => void;
  onTestPassed: () => void;
  /** Bring the Test connection panel into view (the Overview's checklist links here). */
  focusTest?: boolean;
};

type Catalog = { models: CatalogModel[]; error: string };

/** The model catalog, read once the detection mode is "model" (it needs the Models menu). */
function useModelCatalog(wanted: boolean): Catalog | null {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  useEffect(() => {
    if (!wanted || catalog) return;
    let live = true;
    exchangeAdminApi
      .models()
      .then((rows) => {
        if (live) setCatalog({ models: Array.isArray(rows) ? rows : [], error: "" });
      })
      .catch((err: unknown) => {
        if (live) setCatalog({ models: [], error: errorText(err) });
      });
    return () => {
      live = false;
    };
  }, [wanted, catalog]);
  return catalog;
}

/** Fields drawn only for some choices: a refusal about a hidden one is shown above the form. */
function isShown(field: SettingsField, form: ExchangeSettings): boolean {
  if (field === "netbios_domain") return form.login_format === "netbios";
  if (field === "upn_suffix") return form.login_format === "upn";
  if (field === "detection_model") return form.detection === "model";
  return true;
}

/**
 * Exchange EWS › Settings: the connection, what the chat may do,
 * notifications and limits, saved as one object (PUT), and the Test
 * connection panel that tries the saved settings with an account typed in.
 */
export default function ExchangeSettingsTab({
  data,
  loadError,
  onRetry,
  canEdit,
  canEditEndpoint,
  onSaved,
  onTestPassed,
  focusTest,
}: Props) {
  const { confirm } = useConfirm();
  const [form, setForm] = useState<ExchangeSettings | null>(data?.settings ?? null);
  const [serverErrors, setServerErrors] = useState<SettingsErrors>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  /** The server's 403 `super_admin_only`, shown with the controls it is about. */
  const [endpointError, setEndpointError] = useState("");
  const errors = useMemo(() => (form ? validateExchangeSettings(form) : {}), [form]);
  const dirty = useMemo(
    () => Boolean(form && data && JSON.stringify(form) !== JSON.stringify(data.settings)),
    [form, data],
  );
  const catalog = useModelCatalog(form?.detection === "model");
  const ready = form != null;

  useEffect(() => {
    if (focusTest && ready) document.getElementById("ews-admin-test")?.scrollIntoView?.({ block: "start" });
  }, [focusTest, ready]);

  if (!form || !data) {
    return loadError ? (
      <div className="alert alert-error ews-admin-load-error" role="alert">
        <span>The settings could not be read: {loadError}</span>{" "}
        {onRetry ? (
          <button type="button" className="btn btn-ghost btn-sm btn-readonly-ok" onClick={onRetry}>
            Try again
          </button>
        ) : null}
      </div>
    ) : (
      <p className="muted-text">Loading the settings…</p>
    );
  }

  const locked = !canEdit;
  const endpointLocked = locked || !canEditEndpoint;
  // The note the four Super Admin controls point to, for a writer who may not change them.
  const endpointNote = canEdit && !canEditEndpoint ? "ews-endpoint-note" : undefined;
  const withNote = (ids: string | undefined) => [ids, endpointNote].filter(Boolean).join(" ") || undefined;
  const set = (patch: Partial<ExchangeSettings>) => {
    setForm({ ...form, ...patch });
    setNotice("");
    setServerErrors((current) => {
      const next = { ...current };
      for (const key of Object.keys(patch) as SettingsField[]) delete next[key];
      return next;
    });
  };
  const shown = (key: SettingsField): string | undefined => errors[key] ?? serverErrors[key];

  async function save() {
    if (!form || !data || locked || Object.keys(errors).length) return;
    if (resetsPasswords(data.settings, form)) {
      const ok = await confirm({
        title: "Change the connection settings?",
        message: PASSWORDS_RESET_TEXT,
        confirmLabel: "Save settings",
        danger: true,
      });
      if (ok !== true) return;
    }
    setSaving(true);
    setError("");
    setEndpointError("");
    setNotice("");
    try {
      const next = await exchangeAdminApi.saveSettings(form);
      setForm(next.settings);
      setServerErrors({});
      setNotice("Settings saved.");
      onSaved(next);
    } catch (err) {
      const message = errorText(err);
      if (err instanceof MailApiError && err.code === "super_admin_only") {
        setEndpointError(err.serverMessage ? message : ONLY_SUPER_ADMIN_TEXT);
        return;
      }
      const field =
        err instanceof MailApiError && err.code === "invalid_settings"
          ? fieldForServerMessage(message, Object.keys(form) as SettingsField[])
          : null;
      if (field && isShown(field, form)) setServerErrors({ [field]: message });
      else setError(message);
    } finally {
      setSaving(false);
    }
  }

  function discard() {
    if (!data) return;
    setForm(data.settings);
    setServerErrors({});
    setError("");
    setEndpointError("");
    setNotice("");
  }

  const example = exampleLogin(form, data);
  const certificates = countCertificates(form.ca_bundle_pem);
  const textModels = (catalog?.models ?? []).filter((m) => m.enabled && (m.kinds ?? []).includes("text"));
  const modelOptions = textModels.map((m) => ({
    value: String(m.id),
    label: `${m.display_name || m.external_id} · ${m.provider}`,
  }));
  const staleModel =
    catalog && !catalog.error && form.detection_model && !modelOptions.some((o) => o.value === form.detection_model);
  const errorCount = new Set([...Object.keys(errors), ...Object.keys(serverErrors)]).size;
  const clientErrorCount = Object.keys(errors).length;

  return (
    <div className="ews-admin-settings-wrap">
      {locked ? (
        <p className="alert alert-info ews-admin-readonly">Your role can read these settings but not change them.</p>
      ) : null}
      {error ? (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="ews-admin-settings">
        <section className="ews-admin-card ews-admin-card--connection" aria-labelledby="ews-admin-connection-title">
          <h3 id="ews-admin-connection-title">
            Connection
            <Switch on={form.enabled} label="Exchange EWS on" disabled={locked} onChange={(on) => set({ enabled: on })} />
          </h3>
          <p className="muted-text">
            On: people who sign in with Active Directory see <strong>Connections</strong> in their profile menu and can
            connect their mailbox. Off hides it again; nothing is deleted.
          </p>
          {endpointNote ? (
            <p className="alert alert-info ews-admin-warning" id={endpointNote}>
              {ONLY_SUPER_ADMIN_TEXT} The EWS and Autodiscover addresses and the certificate settings are read-only for
              your role.
            </p>
          ) : null}
          {endpointError ? (
            <p className="alert alert-error ews-admin-warning" role="alert">
              {endpointError}
            </p>
          ) : null}

          <Field
            id="ews-url"
            label="EWS address"
            error={shown("ews_url")}
            hint={
              <>
                For example <code dir="ltr">{EWS_URL_EXAMPLE}</code>. A bare https://mail.corp.example is completed with
                /EWS/Exchange.asmx.
                {data.ews_endpoint && form.ews_url === data.settings.ews_url ? (
                  <>
                    {" "}
                    In use: <code dir="ltr">{data.ews_endpoint}</code>
                  </>
                ) : null}
              </>
            }
          >
            <input
              id="ews-url"
              className={`input-block${shown("ews_url") ? " is-invalid" : ""}`}
              dir="ltr"
              inputMode="url"
              value={form.ews_url}
              placeholder={EWS_URL_EXAMPLE}
              autoComplete="off"
              spellCheck={false}
              disabled={endpointLocked}
              aria-invalid={Boolean(shown("ews_url"))}
              aria-describedby={withNote(describedBy("ews-url", true, shown("ews_url")))}
              onChange={(e) => set({ ews_url: e.target.value })}
            />
          </Field>
          <Field
            id="ews-autodiscover"
            label={
              <>
                Autodiscover address <span className="muted-text">(optional)</span>
              </>
            }
            error={shown("autodiscover_url")}
            hint={
              <>
                Lists each person&apos;s Full Access mailboxes, as Outlook does. Blank:{" "}
                <code dir="ltr">{data.autodiscover_endpoint || "https://<EWS host>/autodiscover/autodiscover.xml"}</code>
              </>
            }
          >
            <input
              id="ews-autodiscover"
              className={`input-block${shown("autodiscover_url") ? " is-invalid" : ""}`}
              dir="ltr"
              inputMode="url"
              value={form.autodiscover_url}
              placeholder="https://mail.corp.example/autodiscover/autodiscover.xml"
              autoComplete="off"
              spellCheck={false}
              disabled={endpointLocked}
              aria-invalid={Boolean(shown("autodiscover_url"))}
              aria-describedby={withNote(describedBy("ews-autodiscover", true, shown("autodiscover_url")))}
              onChange={(e) => set({ autodiscover_url: e.target.value })}
            />
          </Field>

          <fieldset className="ews-admin-radios" aria-describedby="ews-login-example">
            <legend>Login format</legend>
            {LOGIN_FORMAT_OPTIONS.map((option) => (
              <label key={option.value} className={`ews-admin-check${locked ? " is-disabled" : ""}`}>
                <input
                  type="radio"
                  name="ews-login-format"
                  value={option.value}
                  checked={form.login_format === option.value}
                  disabled={locked}
                  onChange={() => set({ login_format: option.value })}
                />
                <span>
                  <span className="ews-admin-check__title">{option.label}</span>
                  <span className="ews-admin-hint" dir="ltr">
                    {option.hint}
                  </span>
                </span>
              </label>
            ))}
            <p id="ews-login-example" className="ews-admin-example">
              {example.login ? (
                <>
                  Your own login would be <code dir="ltr">{example.login}</code>
                  {example.saved ? "" : " (after saving)"}. Each person&apos;s login is made the same way from their
                  account and cannot be edited.
                </>
              ) : form.login_format === "email" ? (
                "Each person signs in with the email address of their account in the directory."
              ) : (
                <span className="ews-admin-hint--warn">
                  No login can be made yet: enter the {form.login_format === "netbios" ? "NetBIOS domain" : "UPN suffix"}.
                </span>
              )}
            </p>
            <FieldError text={shown("login_format")} />
          </fieldset>

          {form.login_format === "netbios" ? (
            <Field
              id="ews-netbios"
              label={
                <>
                  NetBIOS domain <span className="muted-text">(optional)</span>
                </>
              }
              error={shown("netbios_domain")}
              hint={
                data.directory.netbios_domain
                  ? `Blank: ${data.directory.netbios_domain}, from the LDAP settings.`
                  : "The LDAP settings do not say which domain: enter it, such as CORP."
              }
            >
              <input
                id="ews-netbios"
                className={`input-block${shown("netbios_domain") ? " is-invalid" : ""}`}
                dir="ltr"
                value={form.netbios_domain}
                placeholder={data.directory.netbios_domain || "CORP"}
                autoComplete="off"
                spellCheck={false}
                disabled={locked}
                aria-invalid={Boolean(shown("netbios_domain"))}
                aria-describedby={describedBy("ews-netbios", true, shown("netbios_domain"))}
                onChange={(e) => set({ netbios_domain: e.target.value })}
              />
            </Field>
          ) : null}
          {form.login_format === "upn" ? (
            <Field
              id="ews-upn"
              label={
                <>
                  UPN suffix <span className="muted-text">(optional)</span>
                </>
              }
              error={shown("upn_suffix")}
              hint={
                data.directory.dns_domain
                  ? `Blank: ${data.directory.dns_domain}, from the LDAP settings.`
                  : "The LDAP settings do not say which domain: enter it, such as corp.example."
              }
            >
              <input
                id="ews-upn"
                className={`input-block${shown("upn_suffix") ? " is-invalid" : ""}`}
                dir="ltr"
                value={form.upn_suffix}
                placeholder={data.directory.dns_domain || "corp.example"}
                autoComplete="off"
                spellCheck={false}
                disabled={locked}
                aria-invalid={Boolean(shown("upn_suffix"))}
                aria-describedby={describedBy("ews-upn", true, shown("upn_suffix"))}
                onChange={(e) => set({ upn_suffix: e.target.value })}
              />
            </Field>
          ) : null}

          <CheckField
            checked={form.require_mailbox_match}
            title="The password must open the person's own mailbox"
            hint="Recommended. The mailbox the login opens is compared with the account's email, so nobody can connect with someone else's password."
            disabled={locked}
            onChange={(on) => set({ require_mailbox_match: on })}
          />
          {!form.require_mailbox_match ? (
            <p className="alert alert-warning ews-admin-warning">
              <strong>Mailbox not checked.</strong> Anyone who knows another person&apos;s AD password could connect that
              mailbox to their own account.
            </p>
          ) : null}
          <CheckField
            checked={form.verify_tls}
            title="Verify the Exchange server's certificate"
            hint="Recommended. For a certificate from an internal CA, paste the CA below rather than turning this off."
            disabled={endpointLocked}
            onChange={(on) => set({ verify_tls: on })}
          />
          {!form.verify_tls ? (
            <p className="alert alert-error ews-admin-warning" data-testid="ews-tls-warning">
              <strong>Certificate not verified.</strong> Anyone able to intercept the connection could pose as Exchange
              and collect the AD passwords people enter. Use this only for a short test on a network you trust.
            </p>
          ) : null}
          <Field
            id="ews-ca"
            label={
              <>
                CA certificates <span className="muted-text">(optional)</span>
              </>
            }
            error={shown("ca_bundle_pem")}
            hint={
              certificates
                ? `${certificates} ${certificates === 1 ? "certificate" : "certificates"}, trusted besides the system's own.`
                : "PEM text of the internal CA that signed the Exchange certificate (root and any intermediate), trusted besides the system's own."
            }
          >
            <textarea
              id="ews-ca"
              className={`input-block ews-admin-pem${shown("ca_bundle_pem") ? " is-invalid" : ""}`}
              rows={4}
              dir="ltr"
              value={form.ca_bundle_pem}
              placeholder="-----BEGIN CERTIFICATE-----"
              spellCheck={false}
              disabled={endpointLocked}
              aria-invalid={Boolean(shown("ca_bundle_pem"))}
              aria-describedby={withNote(describedBy("ews-ca", true, shown("ca_bundle_pem")))}
              onChange={(e) => set({ ca_bundle_pem: e.target.value })}
            />
          </Field>
        </section>

        <ExchangeTestPanel saved={data} dirty={dirty} canRun={canEdit} onPassed={onTestPassed} />

        <section className="ews-admin-card ews-admin-card--chat" aria-labelledby="ews-admin-chat-title">
          <h3 id="ews-admin-chat-title">What the chat may do</h3>
          <p className="muted-text">
            Reading, searching and summarising are always on for a connected mailbox. The model can never send an email
            by itself.
          </p>
          <CheckField
            checked={form.allow_full_access}
            title="Full Access mailboxes"
            hint="Mailboxes a person has Full Access to, listed by Autodiscover as Outlook lists them."
            disabled={locked}
            onChange={(on) => set({ allow_full_access: on })}
          />
          <CheckField
            checked={form.allow_manual_mailboxes}
            title="Let people add a Full Access mailbox by hand"
            hint={
              form.allow_full_access
                ? "For mailboxes given with -AutoMapping $false. Each one is test-read before it is added."
                : "Needs Full Access mailboxes on."
            }
            disabled={locked || !form.allow_full_access}
            onChange={(on) => set({ allow_manual_mailboxes: on })}
          />
          <CheckField
            checked={form.allow_drafts}
            title="Save drafts"
            hint="New emails, replies, reply all and forwards, saved in the mailbox's Drafts folder."
            disabled={locked}
            onChange={(on) => set({ allow_drafts: on })}
          />
          <CheckField
            checked={form.allow_send}
            title="Send after review"
            hint="The person reads the draft in the chat and clicks Send. Off: drafts are sent from Outlook."
            disabled={locked}
            onChange={(on) => set({ allow_send: on })}
          />
          <CheckField
            checked={form.allow_free_time}
            title="Find meeting times"
            hint="Reads the free/busy times of the people asked about; nothing is written to a calendar."
            disabled={locked}
            onChange={(on) => set({ allow_free_time: on })}
          />
        </section>

        <section className="ews-admin-card ews-admin-card--notify" aria-labelledby="ews-admin-notify-title">
          <h3 id="ews-admin-notify-title">
            Notifications
            <Switch
              on={form.notify_enabled}
              label="Notifications on"
              disabled={locked}
              onChange={(on) => set({ notify_enabled: on })}
            />
          </h3>
          <p className="muted-text">
            Checks each connected Inbox for new emails that need the person&apos;s action and tells them with a toast and
            on Connections. Each person can turn it off for themselves.
          </p>
          <NumberField
            id="ews-poll"
            label="Check every (minutes)"
            value={form.poll_minutes}
            bounds={SETTING_BOUNDS.poll_minutes}
            error={shown("poll_minutes")}
            disabled={locked}
            onChange={(v) => set({ poll_minutes: v })}
          />
          <fieldset className="ews-admin-radios">
            <legend>How emails are picked</legend>
            <label className={`ews-admin-check${locked ? " is-disabled" : ""}`}>
              <input
                type="radio"
                name="ews-detection"
                value="rules"
                checked={form.detection === "rules"}
                disabled={locked}
                onChange={() => set({ detection: "rules" })}
              />
              <span>
                <span className="ews-admin-check__title">Rules</span>
                <span className="ews-admin-hint">
                  No model cost. Unread, addressed to the person, not automated, and important, flagged, a meeting
                  request or asking something of them.
                </span>
              </span>
            </label>
            <label className={`ews-admin-check${locked ? " is-disabled" : ""}`}>
              <input
                type="radio"
                name="ews-detection"
                value="model"
                checked={form.detection === "model"}
                disabled={locked}
                onChange={() => set({ detection: "model" })}
              />
              <span>
                <span className="ews-admin-check__title">A model</span>
                <span className="ews-admin-hint">
                  Reads the subject, sender and opening of each email the rules let through, and decides. Billed as a
                  system operation, like memory extraction; Guardrails apply. If it fails, the rules decide.
                </span>
              </span>
            </label>
          </fieldset>
          {form.detection === "model" ? (
            <Field id="ews-detection-model" label="Model" error={shown("detection_model")}>
              <SearchableModelSelect
                id="ews-detection-model"
                ariaLabel="Detection model"
                value={form.detection_model}
                disabled={locked}
                emptyLabel="Not chosen"
                placeholder="Search models…"
                options={modelOptions}
                onChange={(next) => set({ detection_model: next })}
              />
              {catalog == null ? (
                <p className="ews-admin-hint">Loading the models…</p>
              ) : catalog.error ? (
                <p className="ews-admin-hint ews-admin-hint--warn">The model list could not be read: {catalog.error}</p>
              ) : staleModel ? (
                <p className="ews-admin-hint ews-admin-hint--warn">
                  The chosen model is not an enabled text model any more: until another is chosen, the rules decide.
                </p>
              ) : null}
            </Field>
          ) : null}
        </section>

        <section className="ews-admin-card ews-admin-card--limits" aria-labelledby="ews-admin-limits-title">
          <h3 id="ews-admin-limits-title">Limits</h3>
          <NumberField
            id="ews-search-limit"
            label="Results per search"
            value={form.search_limit}
            bounds={SETTING_BOUNDS.search_limit}
            error={shown("search_limit")}
            disabled={locked}
            onChange={(v) => set({ search_limit: v })}
          />
          <NumberField
            id="ews-body-chars"
            label="Characters of email text per read"
            hint="All emails read at once share it."
            value={form.body_chars}
            bounds={SETTING_BOUNDS.body_chars}
            error={shown("body_chars")}
            disabled={locked}
            onChange={(v) => set({ body_chars: v })}
          />
          <NumberField
            id="ews-timeout"
            label="Time limit per Exchange call (seconds)"
            value={form.timeout_s}
            bounds={SETTING_BOUNDS.timeout_s}
            error={shown("timeout_s")}
            disabled={locked}
            onChange={(v) => set({ timeout_s: v })}
          />
          <NumberField
            id="ews-max-mailboxes"
            label="Full Access mailboxes per person"
            hint="Besides their own mailbox, which is not counted."
            value={form.max_mailboxes}
            bounds={SETTING_BOUNDS.max_mailboxes}
            error={shown("max_mailboxes")}
            disabled={locked}
            onChange={(v) => set({ max_mailboxes: v })}
          />
          <NumberField
            id="ews-retention"
            label="Keep action items (days)"
            value={form.action_retention_days}
            bounds={SETTING_BOUNDS.action_retention_days}
            error={shown("action_retention_days")}
            disabled={locked}
            onChange={(v) => set({ action_retention_days: v })}
          />
        </section>
      </div>

      {canEdit ? (
        <div className="ews-admin-savebar">
          <span className={`ews-admin-savebar__state${notice ? " is-saved" : ""}`} aria-live="polite">
            {notice
              ? notice
              : errorCount
                ? `${errorCount} ${errorCount === 1 ? "field needs" : "fields need"} a fix before saving.`
                : dirty
                  ? "Unsaved changes."
                  : "No changes."}
          </span>
          <button type="button" className="btn btn-ghost" disabled={!dirty || saving} onClick={discard}>
            Discard
          </button>
          <button
            type="button"
            className="btn"
            disabled={!dirty || saving || clientErrorCount > 0}
            onClick={() => void save()}
          >
            {saving ? "Saving…" : "Save settings"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
