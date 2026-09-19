import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import Modal from "./Modal";
import ModelName from "./ModelName";
import { formatLocalDateTime } from "../lib/dateTime";
import {
  confidenceLabel,
  errorCodeLabel,
  formatTokenCount,
  logIdentityLabel,
  money,
  type CostDetails,
  type RequestLogSummary,
} from "../lib/requestLogCostDetails";

type Props = {
  open: boolean;
  log: RequestLogSummary | null;
  details: CostDetails | null;
  loading: boolean;
  error: string;
  onClose: () => void;
  /** Optional admin-only export control. */
  exportSlot?: ReactNode;
  exportError?: string;
};

export default function RequestLogCostDetailsModal({
  open,
  log,
  details,
  loading,
  error,
  onClose,
  exportSlot,
  exportError,
}: Props) {
  const fmt = formatTokenCount;

  return (
    <Modal
      open={open}
      title={log ? `Cost details · #${log.id}` : "Cost details"}
      onClose={onClose}
      panelClassName="modal-panel--cost-details"
    >
      {log && (
        <div className="api-log-cost-details">
          {exportSlot ? <div className="api-log-cost-details__actions">{exportSlot}</div> : null}
          {exportError ? <p className="error" role="alert">{exportError}</p> : null}
          <div className="api-log-cost-details__summary">
            <div>
              <span className="muted">Time</span>
              <strong>{formatLocalDateTime(log.request_time)}</strong>
            </div>
            <div>
              <span className="muted">User / API key</span>
              <strong>{logIdentityLabel(log)}</strong>
            </div>
            <div>
              <span className="muted">Model</span>
              <strong>
                <ModelName modelId={log.model_id} label={log.model_id} size={14} />
              </strong>
            </div>
            <div>
              <span className="muted">Logged cost</span>
              <strong>{money(log.total_cost_usd)}</strong>
            </div>
            <div>
              <span className="muted">Quality</span>
              <strong>
                <span
                  className={`api-log-cost-quality api-log-cost-quality--${
                    confidenceLabel(log.cost_confidence || "unknown", !!log.has_unpriced_usage).key
                  }`}
                >
                  {
                    confidenceLabel(log.cost_confidence || "unknown", !!log.has_unpriced_usage)
                      .label
                  }
                </span>
              </strong>
            </div>
          </div>

          {loading && <p className="muted">Loading cost ledger…</p>}
          {error && <p className="error" role="alert">{error}</p>}

          {!loading && !error && details?.request && !details.request.success && (
            <div className="api-log-cost-details__failure">
              <h4>Failure</h4>
              <dl>
                <div>
                  <dt>Reason</dt>
                  <dd>{errorCodeLabel(details.request.error_code) || "Unknown"}</dd>
                </div>
                {details.request.http_status != null && (
                  <div>
                    <dt>HTTP status</dt>
                    <dd>{details.request.http_status}</dd>
                  </div>
                )}
                {details.request.provider_job_id && (
                  <div>
                    <dt>Provider job</dt>
                    <dd className="api-log-cost-details__mono">{details.request.provider_job_id}</dd>
                  </div>
                )}
                {details.request.correlation_id && (
                  <div>
                    <dt>Correlation id</dt>
                    <dd
                      className="api-log-cost-details__mono"
                      title="Search the server logs for this id to see every line from this request"
                    >
                      {details.request.correlation_id}
                    </dd>
                  </div>
                )}
              </dl>
              {details.request.error_message && (
                <p className="api-log-cost-details__error-text">{details.request.error_message}</p>
              )}
            </div>
          )}

          {!loading && !error && details?.legacy && (
            <p className="muted">
              This request was logged before the usage ledger. Only the summary total is available (
              {money(details.total_cost_usd ?? log.total_cost_usd)}).
            </p>
          )}

          {!loading && !error && details && !details.legacy && (
            <>
              {details.operation && (
                <div className="api-log-cost-details__operation">
                  <h4>Operation</h4>
                  <dl>
                    <div>
                      <dt>Type</dt>
                      <dd>{details.operation.operation_type}</dd>
                    </div>
                    <div>
                      <dt>Status</dt>
                      <dd>{details.operation.status}</dd>
                    </div>
                    <div>
                      <dt>Total</dt>
                      <dd>{money(details.operation.total_cost_usd)}</dd>
                    </div>
                    <div>
                      <dt>Provider</dt>
                      <dd>{money(details.operation.provider_cost_usd)}</dd>
                    </div>
                    <div>
                      <dt>Calculated</dt>
                      <dd>{money(details.operation.calculated_cost_usd)}</dd>
                    </div>
                    <div>
                      <dt>Unpriced events</dt>
                      <dd>{details.operation.unpriced_event_count}</dd>
                    </div>
                    {details.operation.reconciled_at && (
                      <div>
                        <dt>Reconciled</dt>
                        <dd>{formatLocalDateTime(details.operation.reconciled_at)}</dd>
                      </div>
                    )}
                  </dl>
                </div>
              )}

              <div className="api-log-cost-details__events">
                <h4>Upstream attempts ({details.events.length})</h4>
                {details.events.length === 0 && (
                  <p className="muted">No usage events were recorded for this operation.</p>
                )}
                {details.events.map((event) => {
                  const quality = confidenceLabel(event.cost_confidence || "unknown");
                  return (
                    <article key={event.id} className="api-log-cost-event">
                      <header>
                        <div>
                          <strong>
                            Attempt {event.attempt_index} · {event.operation_name || event.service_type}
                          </strong>
                          <span className="muted">
                            {event.provider_type}
                            {event.model_id ? ` · ${event.model_id}` : ""}
                            {` · ${event.status}`}
                          </span>
                        </div>
                        <span className={`api-log-cost-quality api-log-cost-quality--${quality.key}`}>
                          {quality.label}
                        </span>
                      </header>
                      <dl>
                        <div>
                          <dt>Final</dt>
                          <dd>{money(event.final_cost_usd)}</dd>
                        </div>
                        <div>
                          <dt>Provider</dt>
                          <dd>{money(event.provider_cost_usd)}</dd>
                        </div>
                        <div>
                          <dt>Calculated</dt>
                          <dd>{money(event.calculated_cost_usd)}</dd>
                        </div>
                        <div>
                          <dt>Source</dt>
                          <dd>{event.cost_source || "—"}</dd>
                        </div>
                        <div className="api-log-cost-event__full">
                          <dt>Tokens</dt>
                          <dd>
                            {fmt(event.prompt_tokens || 0)} in / {fmt(event.completion_tokens || 0)} out
                            {(event.cached_tokens || 0) > 0 ? ` · ${fmt(event.cached_tokens)} cached` : ""}
                            {(event.reasoning_tokens || 0) > 0
                              ? ` · ${fmt(event.reasoning_tokens)} reasoning`
                              : ""}
                          </dd>
                        </div>
                        {event.upstream_request_id && (
                          <div className="api-log-cost-event__full">
                            <dt>Upstream ID</dt>
                            <dd>
                              <code className="api-log-cost-event__id">{event.upstream_request_id}</code>
                            </dd>
                          </div>
                        )}
                        {event.connection_id != null && (
                          <div>
                            <dt>Connection</dt>
                            <dd>#{event.connection_id}</dd>
                          </div>
                        )}
                        {event.quantity != null && (
                          <div>
                            <dt>Quantity</dt>
                            <dd>
                              {event.quantity} {event.unit || ""}
                            </dd>
                          </div>
                        )}
                        {event.started_at && (
                          <div>
                            <dt>Started</dt>
                            <dd>{formatLocalDateTime(event.started_at)}</dd>
                          </div>
                        )}
                        {event.raw_usage && (
                          <div className="api-log-cost-event__full">
                            <dt>Provider response</dt>
                            <dd>
                              <details className="api-log-cost-event__raw">
                                <summary>Show raw payload</summary>
                                <pre>{JSON.stringify(event.raw_usage, null, 2)}</pre>
                                {details.raw_payload_retention_days ? (
                                  <p className="api-log-cost-event__raw-note muted-text">
                                    Kept for {details.raw_payload_retention_days} days ·{" "}
                                    <Link to="/admin/retention-policy">Retention Policy</Link>
                                  </p>
                                ) : null}
                              </details>
                            </dd>
                          </div>
                        )}
                        {event.error_message && (
                          <div className="api-log-cost-event__full">
                            <dt>Error</dt>
                            <dd>{event.error_message}</dd>
                          </div>
                        )}
                      </dl>
                      {event.line_items.length > 0 && (
                        <div className="api-log-cost-lines-wrap">
                          <table className="api-log-cost-lines">
                            <thead>
                              <tr>
                                <th>Category</th>
                                <th>Qty</th>
                                <th>Unit price</th>
                                <th>Cost</th>
                                <th>Pricing</th>
                              </tr>
                            </thead>
                            <tbody>
                              {event.line_items.map((line, idx) => (
                                <tr key={`${event.id}-${line.category}-${idx}`}>
                                  <td>{line.category}</td>
                                  <td>
                                    {fmt(line.quantity)} {line.unit}
                                  </td>
                                  <td>{money(line.unit_price_usd)}</td>
                                  <td>{money(line.cost_usd)}</td>
                                  <td>{line.pricing_source || "—"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            </>
          )}
        </div>
      )}
    </Modal>
  );
}
