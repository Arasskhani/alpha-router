import { ReactNode } from "react";

export type DocSection = {
  id: string;
  title: string;
  group?: string;
  content: ReactNode;
};

function Note({ children }: { children: ReactNode }) {
  return <div className="docs-callout docs-callout-info">{children}</div>;
}

function Warn({ children }: { children: ReactNode }) {
  return <div className="docs-callout docs-callout-warn">{children}</div>;
}

export const userManualSections: DocSection[] = [
  // ── Get started ───────────────────────────────────────────────────────────
  {
    id: "introduction",
    title: "Introduction",
    group: "Get started",
    content: (
      <>
        <h1>User Manual</h1>
        <p className="docs-lead">
          Welcome to alpharouter — your organization’s AI workspace. Use approved models in Chat, keep generated files in
          Media, and track your own spend under Activity. Administrators configure models, budgets, and
          sign-in; this manual covers what you can do in the <strong>/app</strong> panel after you sign in.
        </p>
        <div className="docs-cards">
          <div className="docs-card">
            <h3>Chat</h3>
            <p>Sessions, folders, tools, voice, images, private mode, export, and a prompt queue.</p>
          </div>
          <div className="docs-card">
            <h3>Media</h3>
            <p>Files you upload or generate, with search, filters, and optional cleanup.</p>
          </div>
          <div className="docs-card">
            <h3>Activity</h3>
            <p>Your spend, tokens, models, and CSV/PDF export.</p>
          </div>
        </div>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Section</th>
              <th>Contents</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <a href="#sign-in">Sign-in</a> &amp; <a href="#app-tour">App tour</a>
              </td>
              <td>How you authenticate and navigate <code>/app</code></td>
            </tr>
            <tr>
              <td>
                <a href="#user-chat">Chat</a>
              </td>
              <td>Sessions, models, streaming, attachments, tools, private mode</td>
            </tr>
            <tr>
              <td>
                <a href="#user-media">Media</a> · <a href="#user-activity">Activity</a> ·{" "}
                <a href="#user-settings">Settings</a>
              </td>
              <td>Library, activity, account preferences and security</td>
            </tr>
          </tbody>
        </table>
      </>
    ),
  },
  {
    id: "sign-in",
    title: "Sign-in",
    group: "Get started",
    content: (
      <>
        <h2>Sign-in</h2>
        <p>
          Open the alpharouter URL your administrator gave you and sign in on <code>/login</code>. Depending on your
          organization you may see:
        </p>
        <ul>
          <li>
            <strong>Local account</strong> — username and password. If 2FA is enabled, enter the authenticator code (or
            a backup code) after the password.
          </li>
          <li>
            <strong>Active Directory / LDAP</strong> — same username/password form; alpharouter validates against your
            directory.
          </li>
          <li>
            <strong>SSO</strong> — SAML or OIDC buttons that redirect to your company identity provider, then return you
            to alpharouter.
          </li>
        </ul>
        <Note>
          If sign-in fails, contact your administrator — they control which methods are enabled and whether your account
          is active.
        </Note>
      </>
    ),
  },
  {
    id: "app-tour",
    title: "Tour of /app",
    group: "Get started",
    content: (
      <>
        <h2>Tour of /app</h2>
        <p>After sign-in you land in the user panel. Main navigation:</p>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Item</th>
              <th>Purpose</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <strong>Chat</strong>
              </td>
              <td>
                <code>/app/chat</code> — conversations with AI models
              </td>
            </tr>
            <tr>
              <td>
                <strong>Media</strong>
              </td>
              <td>
                <code>/app/media</code> — your uploads and generated files
              </td>
            </tr>
            <tr>
              <td>
                <strong>Activity</strong>
              </td>
              <td>
                <code>/app/my-activity</code> — personal spend and usage
              </td>
            </tr>
            <tr>
              <td>
                <strong>User Manual</strong>
              </td>
              <td>
                <code>/app/manual</code> — this guide
              </td>
            </tr>
          </tbody>
        </table>
        <h3>Top bar</h3>
        <ul>
          <li>
            <strong>alpharouter</strong> brand / home context
          </li>
          <li>
            On Chat: model search / picker controls when available
          </li>
          <li>
            Theme control (light / dark / system) and your <strong>profile menu</strong>
          </li>
        </ul>
        <h3>Profile menu</h3>
        <ul>
          <li>
            Monthly <strong>Budget</strong> (used vs limit) when a plan is assigned
          </li>
          <li>
            <strong>Settings</strong> — general preferences, data control, security
          </li>
          <li>
            <strong>Sign out</strong>
          </li>
          <li>
            If you also have admin roles: <strong>Administration</strong> opens <code>/admin</code>
          </li>
        </ul>
        <Note>
          On Chat, the left app sidebar can appear as a peek rail — hover to expand navigation without leaving the
          conversation.
        </Note>
      </>
    ),
  },

  // ── Chat ──────────────────────────────────────────────────────────────────
  {
    id: "user-chat",
    title: "Chat overview",
    group: "Chat",
    content: (
      <>
        <h2>Chat overview</h2>
        <p>
          Path: <code>/app/chat</code>. Create multiple sessions, organize them into folders, pick models your admin
          enabled, and stream replies. Your chats sync to the server (except <a href="#private-mode">Private mode</a>
          ).
        </p>
        <ul>
          <li>
            <a href="#chat-sessions">Sessions &amp; folders</a>
          </li>
          <li>
            <a href="#chat-models">Models</a>
          </li>
          <li>
            <a href="#chat-streaming">Sending, streaming &amp; queue</a>
          </li>
          <li>
            <a href="#chat-attachments">Attachments &amp; voice</a>
          </li>
          <li>
            <a href="#chat-images">Image generation</a>
            {" · "}
            <a href="#chat-videos">Video generation</a>
          </li>
          <li>
            <a href="#chat-tools">Chat Tools</a>
          </li>
          <li>
            <a href="#private-mode">Private mode</a>
          </li>
          <li>
            <a href="#chat-export">Export &amp; feedback</a>
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "chat-sessions",
    title: "Sessions &amp; folders",
    group: "Chat",
    content: (
      <>
        <h2>Sessions &amp; folders</h2>
        <ul>
          <li>
            <strong>New chat</strong> starts an empty session. Titles can update automatically from the conversation
            (unless you lock/rename them).
          </li>
          <li>
            Rename, delete, or move sessions into <strong>folders</strong> from the chat sidebar.
          </li>
          <li>
            Sidebar groups recent activity (for example today vs older). Search finds sessions and, when available,
            message content on the server.
          </li>
          <li>
            Switching sessions loads messages as needed. Long threads support scroll-to-bottom when you are not pinned
            to the latest reply.
          </li>
        </ul>
        <Note>
          Composer text and pending attachments are kept as a per-session draft while you switch chats in the same
          browser tab.
        </Note>
      </>
    ),
  },
  {
    id: "chat-models",
    title: "Models",
    group: "Chat",
    content: (
      <>
        <h2>Models</h2>
        <p>
          Only models your administrator enabled appear in the picker. Open the model picker from the chat chrome to
          choose a default model for the session. Some deployments allow selecting multiple models for a turn (compare
          replies); limits are enforced by the app.
        </p>
        <ul>
          <li>Chat / reasoning models stream text replies.</li>
          <li>Vision-capable models can accept image attachments in the prompt.</li>
          <li>Image models are used for generation (see <a href="#chat-images">Image generation</a>).</li>
        </ul>
        <p>
          You can save a preferred default model in Settings (or via the picker when that option is offered). Budget and
          model availability are organization policy — contact an admin if a model is missing.
        </p>
      </>
    ),
  },
  {
    id: "chat-streaming",
    title: "Sending, streaming &amp; queue",
    group: "Chat",
    content: (
      <>
        <h2>Sending, streaming &amp; queue</h2>
        <ol>
          <li>Type your prompt in the composer (Persian and English are both supported; direction follows the text).</li>
          <li>Send to start a turn. The assistant reply streams token by token.</li>
          <li>
            Use <strong>Stop</strong> to cancel generation for that session. alpharouter still finalizes billing for work
            already done upstream when applicable.
          </li>
        </ol>
        <h3>Prompt queue</h3>
        <p>
          If a session is already generating, new prompts can be queued. They run one after another for that session so
          turns stay ordered. You can review queued items in the composer area while a reply is in progress.
        </p>
        <h3>Read-only</h3>
        <p>
          If your account is deactivated, you can still open old chats but cannot send new messages. See{" "}
          <a href="#user-readonly">Deactivated accounts</a>.
        </p>
        <Warn>
          Sending requires remaining monthly budget. If you see a budget / payment error (HTTP 402), ask an
          administrator to assign or raise your plan.
        </Warn>
      </>
    ),
  },
  {
    id: "chat-attachments",
    title: "Attachments &amp; voice",
    group: "Chat",
    content: (
      <>
        <h2>Attachments &amp; voice</h2>
        <h3>Files</h3>
        <p>
          Attach files from the composer (subject to organization size limits). Text and document attachments are
          processed for the model; images can be sent to vision-capable models. Oversized or blocked types show an
          error before send.
        </p>
        <h3>Voice</h3>
        <ul>
          <li>Record or upload audio for transcription into the composer.</li>
          <li>
            Choose voice recording language in Settings → General (English or Persian) so transcription matches your
            speech.
          </li>
          <li>Optional refine step can clean up a transcript before you send it as a prompt.</li>
        </ul>
      </>
    ),
  },
  {
    id: "chat-images",
    title: "Image generation",
    group: "Chat",
    content: (
      <>
        <h2>Image generation</h2>
        <p>
          When an image-capable model (or image tool flow) is selected, alpharouter generates images through the platform
          image API. Generation can continue in the background for that session; you can navigate away and return while
          a job is pending.
        </p>
        <ul>
          <li>Prompt enhancement / translation helpers may be available from the composer for image prompts.</li>
          <li>Completed images appear in the thread and usually in your Media library (unless Private mode).</li>
          <li>Costs count against your monthly budget like other paid requests.</li>
        </ul>
      </>
    ),
  },
  {
    id: "chat-videos",
    title: "Video generation",
    group: "Chat",
    content: (
      <>
        <h2>Video generation</h2>
        <p>
          Enable <strong>Video Generation</strong> in Chat Tools to create clips from a text prompt (text-to-video) or
          from an attached / prior image as the first frame (image-to-video). Jobs run asynchronously; a pending
          placeholder stays in the thread until the clip is ready.
        </p>
        <ul>
          <li>Choose duration, resolution, and aspect ratio from the tools menu before sending.</li>
          <li>Completed videos appear in the thread and in your Media library (unless Private mode).</li>
          <li>Only one video job runs at a time per user by default; costs count against your monthly budget.</li>
        </ul>
      </>
    ),
  },
  {
    id: "chat-tools",
    title: "Chat Tools",
    group: "Chat",
    content: (
      <>
        <h2>Chat Tools</h2>
        <p>
          Open the tools menu on the composer to enable capabilities for the current session. Availability depends on
          your deployment and model.
        </p>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Tool</th>
              <th>What it does</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <strong>Web search</strong>
              </td>
              <td>Lets the model request web search results (depth settings may apply).</td>
            </tr>
            <tr>
              <td>
                <strong>Web fetch</strong>
              </td>
              <td>Fetches the content of a URL the model chooses (subject to server SSRF protections).</td>
            </tr>
            <tr>
              <td>
                <strong>Image generation</strong>
              </td>
              <td>Enables image generation flows from chat.</td>
            </tr>
            <tr>
              <td>
                <strong>Code interpreter</strong>
              </td>
              <td>
                Runs Python in an isolated sandbox for calculation / data tasks. The model must emit a fenced{" "}
                <code>python</code> code block for anything to execute. Spreadsheet attachments reach the sandbox as CSV
                (use Code interpreter outside Private mode for Excel). Valid PDF, CSV, JSON, text, and Markdown outputs
                are saved to your Media library and shown as authenticated download links in Chat, including files named
                in Persian or any other language. Generated files are
                not persisted in Private mode. Extra budget hold may apply while the tool is on. While the tool is on,
                the model list hides models that were measured as unable to complete this flow; if your current model is
                one of them, Chat switches to a suitable model and tells you why. If all execution slots are occupied,
                Chat reports that Code Interpreter is busy before sending the request to the model; wait for the
                indicated retry interval and try again. Pressing Stop also cancels the active sandbox job.
              </td>
            </tr>
          </tbody>
        </table>
        <Note>
          Tool preferences are remembered per session when you change them. Turn off tools you do not need to avoid
          unexpected calls or cost.
        </Note>
      </>
    ),
  },
  {
    id: "private-mode",
    title: "Private mode",
    group: "Chat",
    content: (
      <>
        <h2>Private mode</h2>
        <p>
          Private mode keeps a chat on your device: sessions and messages stay in local browser storage; media uses
          IndexedDB. alpharouter does <strong>not</strong> persist that session’s messages to the server.
        </p>
        <ul>
          <li>Enabling Private mode requires confirmation and is <strong>not reversible</strong> for that chat.</li>
          <li>Model calls still go through alpharouter (and count toward budget) — only chat history storage is local.</li>
          <li>
            On logout, private chats are cleared unless your browser has persistence explicitly enabled by policy/local
            flag (administrators document this for your site).
          </li>
          <li>Private chats are excluded from Settings → Data Control server export.</li>
        </ul>
        <Warn>
          Private mode is not a substitute for a secure endpoint. Anyone with access to your browser profile may read
          local private data. Use organization SSO and device policies as instructed by your admin.
        </Warn>
      </>
    ),
  },
  {
    id: "chat-export",
    title: "Export &amp; feedback",
    group: "Chat",
    content: (
      <>
        <h2>Export &amp; feedback</h2>
        <h3>Export</h3>
        <p>
          From a conversation you can export content as PDF or DOCX (server-rendered for faithful Persian/RTL layout
          when needed). CSV helpers may be available for tabular markdown in replies.
        </p>
        <h3>Feedback</h3>
        <p>
          Rate assistant outputs (thumbs / reasons when prompted). Feedback helps administrators understand model
          quality; it does not change your budget.
        </p>
        <h3>Regenerate</h3>
        <p>Where offered, regenerate requests a new assistant reply for the same user turn (additional usage applies).</p>
      </>
    ),
  },

  // ── Media ─────────────────────────────────────────────────────────────────
  {
    id: "user-media",
    title: "Media",
    group: "Media",
    content: (
      <>
        <h2>Media</h2>
        <p>
          Path: <code>/app/media</code>. Browse files associated with your account — uploads and generations from chat
          (non-private).
        </p>
        <ul>
          <li>Search and filter by kind or date as offered in the library UI.</li>
          <li>Open, download, or delete individual items; bulk delete and ZIP download when available.</li>
          <li>
            Quota meter shows how much of your storage allowance you use (limit set by administrators).
          </li>
          <li>
            Optional <strong>cleanup schedule</strong>: enable automatic deletion of media older than N days at a time
            you choose.
          </li>
        </ul>
        <Note>
          Global retention policies set by administrators may delete media earlier than your personal schedule. When in
          doubt, download copies you need to keep.
        </Note>
      </>
    ),
  },

  // ── Usage ─────────────────────────────────────────────────────────────────
  {
    id: "user-activity",
    title: "Activity",
    group: "Activity",
    content: (
      <>
        <h2>Activity</h2>
        <p>
          Path: <code>/app/my-activity</code>. Personal analytics for your account only (not the whole organization).
        </p>
        <ul>
          <li>Choose a time period and explore spend, requests, tokens, and models.</li>
          <li>Charts and tables help you see which models or days drive usage.</li>
          <li>Export CSV or PDF for your own records.</li>
        </ul>
        <p>
          Your monthly budget remaining is also visible from the profile menu. Administrators see organization-wide
          dashboards separately.
        </p>
      </>
    ),
  },

  // ── Account ───────────────────────────────────────────────────────────────
  {
    id: "user-settings",
    title: "Settings",
    group: "Account",
    content: (
      <>
        <h2>Settings</h2>
        <p>Open Settings from the profile menu. Four tabs:</p>
        <h3>General</h3>
        <ul>
          <li>Time zone for activity displays</li>
          <li>Voice recording language (English / Persian)</li>
          <li>Theme: light, dark, or system</li>
        </ul>
        <h3>Data Control</h3>
        <ul>
          <li>
            <strong>Export</strong> server-side chats as JSON
          </li>
          <li>
            <strong>Import</strong> JSON from alpharouter, ChatGPT, or Open WebUI formats (merges into your account)
          </li>
        </ul>
        <p>Private-mode chats are not included in server export.</p>
        <h3>Security</h3>
        <ul>
          <li>
            Local accounts: change password; set up or disable TOTP 2FA and store backup codes safely
          </li>
          <li>
            LDAP / SAML / OIDC accounts: password and 2FA are managed at your identity provider
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "user-profile",
    title: "Budget, theme &amp; logout",
    group: "Account",
    content: (
      <>
        <h2>Budget, theme &amp; logout</h2>
        <ul>
          <li>
            <strong>Budget</strong> — monthly USD allowance from your plan. Chat, images, and your personal API keys (if
            any) consume it.
          </li>
          <li>
            <strong>Theme</strong> — follows Settings; applied across the app.
          </li>
          <li>
            <strong>Sign out</strong> — ends your session and revokes prior tokens for your account. Private local data
            is cleared unless persistence is enabled for your browser.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "user-readonly",
    title: "Deactivated accounts",
    group: "Account",
    content: (
      <>
        <h2>Deactivated accounts</h2>
        <p>
          If an administrator deactivates your account, you can still sign in to <strong>read</strong> your existing
          chat history and media, but you cannot send new messages, generate images, or create new spend. Contact your
          administrator to restore access.
        </p>
        <Note>
          This is different from holding an admin role such as API Key Admin. Those roles add admin menus; they do not
          deactivate chat.
        </Note>
      </>
    ),
  },

  // ── Legal ─────────────────────────────────────────────────────────────────
  {
    id: "copyright",
    title: "Copyright",
    group: "Legal",
    content: (
      <>
        <h2>Copyright</h2>
        <p>© 2026 Majid Arasskhani. All rights reserved.</p>
        <p>alpharouter is designed and developed by Majid Arasskhani.</p>
        <p>Unauthorized reproduction, distribution, or modification is prohibited.</p>
        <div style={{ marginTop: "1rem" }}>
          <p style={{ margin: 0 }}>Contact: Majid.Arasskhani@Gmail.com</p>
        </div>
      </>
    ),
  },
];
