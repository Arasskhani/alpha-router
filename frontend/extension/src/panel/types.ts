/** What /api/extension/me answers. */
export type Me = {
  user: { username: string; display_name: string | null; email: string | null };
  server: { name: string; url: string | null };
  extension: { latest_version: string | null; min_version: string };
  features: { chat: boolean; page_context: boolean; agent: boolean; auto_mode: boolean; private_mode: boolean };
  policy: null | {
    site_access: "per_site" | "all_sites";
    allowed_sites: string[];
    blocked_sites: string[];
    page_content_models: string[];
    agent_models: string[];
    agent_max_steps: number;
  };
};
