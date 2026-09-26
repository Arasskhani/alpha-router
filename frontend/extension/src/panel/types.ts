import type { Approvals } from "../lib/agentPolicy";

/** What /api/extension/me answers. */
export type Me = {
  user: { username: string; display_name: string | null; email: string | null };
  server: { name: string; url: string | null };
  extension: { latest_version: string | null; min_version: string };
  features: { chat: boolean; page_context: boolean; agent: boolean; auto_mode: boolean; full_control?: boolean; private_mode: boolean };
  policy: null | {
    site_access: "per_site" | "all_sites";
    allowed_sites: string[];
    blocked_sites: string[];
    /** Sites the agent reads and never acts on. */
    read_only_sites?: string[];
    /** Sites where the agent never acts (payment gateways, banks). */
    protected_sites?: string[];
    page_content_models: string[];
    agent_models: string[];
    agent_max_steps: number;
    /** The sensitive cases that still ask; a missing one asks. */
    approvals?: Partial<Approvals>;
    /** Where content may go: the organisation's internal sites, and the models that may see them and screenshots (null: any). */
    data?: { internal_sites: string[]; internal_models: string[] | null; screenshot_models: string[] | null };
  };
};
