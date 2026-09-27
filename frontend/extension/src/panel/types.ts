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
    /** A run's other limits: minutes, and tabs it may open. */
    agent_max_minutes?: number;
    agent_max_tabs?: number;
    /** The modes on offer, and the one a run starts in unless the person chose another. */
    agent_modes?: string[];
    agent_default_mode?: string;
    /** Screenshots: the longest side, and how many of the latest stay in the conversation. */
    screenshot_max_side?: number;
    screenshots_kept?: number;
    /** Whether finished runs are kept as chats, and whether the person may keep one out. */
    save_runs?: boolean;
    private_runs?: boolean;
    /** The sensitive cases that still ask; a missing one asks. */
    approvals?: Partial<Approvals>;
    /** Where content may go: the organisation's internal sites, and the models that may see them and screenshots (null: any). */
    data?: { internal_sites: string[]; internal_models: string[] | null; screenshot_models: string[] | null };
  };
};
