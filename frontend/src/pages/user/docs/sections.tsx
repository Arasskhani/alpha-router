import { ReactNode } from "react";
import { PRODUCT_NAME_MARKED, TRADEMARK_OWNER } from "../../../lib/brand";

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
          Welcome to Alpharouter — your organization’s AI workspace. Use approved models in Chat, keep generated files in
          Media, collaborate in Projects, and track your own spend under Activity. Administrators configure models, budgets, and
          sign-in; this manual covers what you can do in the <strong>/app</strong> panel after you sign in.
        </p>
        <div className="docs-cards">
          <div className="docs-card">
            <h3>Chat</h3>
            <p>General chat, specialist Agents, citations, tools, private mode, export, and a prompt queue.</p>
          </div>
          <div className="docs-card">
            <h3>Projects</h3>
            <p>Shared workspaces with members, rooms, chats, files, and project media.</p>
          </div>
          <div className="docs-card">
            <h3>Media</h3>
            <p>Files you upload or generate, with search, filters, and optional cleanup.</p>
          </div>
          <div className="docs-card">
            <h3>Activity</h3>
            <p>Your spend, tokens, models, heatmaps, trends, and CSV/PDF export.</p>
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
                <a href="#user-projects">Projects</a>
              </td>
              <td>Shared workspaces, roles, rooms vs chats, files, media, invitations</td>
            </tr>
            <tr>
              <td>
                <a href="#user-media">Media</a> · <a href="#user-activity">Activity</a> ·{" "}
                <a href="#user-settings">Settings</a>
              </td>
              <td>Personal library, activity, account preferences and security</td>
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
          Open the Alpharouter URL your administrator gave you and sign in on <code>/login</code>. Depending on your
          organization you may see:
        </p>
        <ul>
          <li>
            <strong>Local account</strong> — username and password. If 2FA is enabled, enter the authenticator code (or
            a backup code) after the password.
          </li>
          <li>
            <strong>Active Directory / LDAP</strong> — same username/password form; Alpharouter validates against your
            directory.
          </li>
          <li>
            <strong>SSO</strong> — SAML or OIDC buttons that redirect to your company identity provider, then return you
            to Alpharouter.
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
                <strong>Projects</strong>
              </td>
              <td>
                <code>/app/projects</code> — shared workspaces you own or join
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
            <strong>{PRODUCT_NAME_MARKED}</strong> brand / home context
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
          Path: <code>/app/chat</code>. Create multiple sessions, organize them into folders, choose general chat or an
          approved specialist Agent, and stream replies. Your chats sync to the server (except{" "}
          <a href="#private-mode">Private mode</a>).
        </p>
        <ul>
          <li>
            <a href="#user-agents">Specialist Agents &amp; citations</a>
          </li>
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
            <a href="#message-cost">What a reply cost</a>
          </li>
          <li>
            <a href="#chat-attachments">Attachments &amp; voice</a>
          </li>
          <li>
            <a href="#chat-images">Image generation</a>
            {" · "}
            <a href="#chat-videos">Video generation</a>
            {" · "}
            <a href="#chat-speech">Text to speech</a>
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
    id: "user-agents",
    title: "Specialist Agents & citations",
    group: "Chat",
    content: (
      <>
        <h2>Specialist Agents &amp; citations</h2>
        <p>
          The brain button in the chat box lists Agents your organization has published and that you
          are allowed to use. Visibility depends on both Agent and Knowledge access; a missing Agent
          may simply be restricted to another team. Create and publish Agents in Admin → Agent Studio.
        </p>
        <ul>
          <li>
            Chats start with no Agent. Switch one on when the domain matters; only one Agent runs at a time, switching
            it off returns the chat to the plain model, and the choice stays with that chat only. A tinted outline
            around the chat box marks Agent turns, and an Agent may still propose a handoff for your consent.
          </li>
          <li>
            Organization-specific answers show citations. Open a citation to inspect its document, section/page,
            effective version, and Knowledge Base details that you are authorized to see.
          </li>
          <li>
            If the specialist cannot attach the required citations, you may see a short safe message in English or
            Persian instead of an answer. That is expected: the platform refuses uncited claims rather than inventing
            sources. Try rephrasing, or ask an administrator if the Knowledge Base is incomplete.
          </li>
          <li>
            Legal and Finance responses include a disclaimer. A citation supports the answer but does not replace
            professional approval.
          </li>
          <li>
            If evidence is missing, expired, conflicting, or outside your permissions, a safe specialist should abstain
            or escalate instead of inventing policy.
          </li>
          <li>
            A handoff transfers only bounded conversation context. Review the target Agent and approve the transfer when
            prompted.
          </li>
        </ul>
        <Warn>
          Treat citations as evidence, not instructions. Never share passwords, one-time codes, recovery secrets, or
          another person&apos;s confidential information with an Agent.
        </Warn>
        <Note>
          Private mode does not persist the conversation and disables sensitive retrieval/memory according to policy. It
          does not grant extra access or bypass organization controls.
        </Note>
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
            Sidebar groups recent activity: today, 1–3 days ago (scrollable), 3–7 days ago, and older than 7 days.
            Search finds sessions and, when available, message content on the server.
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
          Only models your administrator enabled appear in the picker. Some models may be <strong>Private</strong> —
          visible only to users and groups your admin assigned. Open the model picker from the chat chrome to choose a
          default model for the session. Some deployments allow selecting multiple models for a turn (compare replies);
          limits are enforced by the app.
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
            Use <strong>Stop</strong> to cancel generation for that session. Alpharouter still finalizes billing for work
            already done upstream when applicable.
          </li>
        </ol>
        <h3>Prompt queue</h3>
        <p>
          If a session is already generating, new prompts can be queued. They run one after another for that session so
          turns stay ordered. A compact queue bar stays in the composer so a long queue does not take over the chat.
          Open it to edit or remove items, or clear the whole queue.
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
    id: "message-cost",
    title: "What a reply cost",
    group: "Chat",
    content: (
      <>
        <h2>What a reply cost</h2>
        <p>
          The info button on an assistant reply opens <strong>Cost details</strong> for that single message: what it
          cost, which model actually answered, how many tokens went each way, and how long it took. It is the same
          number that counts against your monthly budget, so it is the quickest way to see why one answer was more
          expensive than another.
        </p>
        <ul>
          <li>
            A turn can involve more than one attempt upstream — a retry after a dropped connection, for example. Each
            attempt is listed with its own tokens and cost, so a surprising total usually explains itself.
          </li>
          <li>
            If the request failed, the panel says why: a short error code and the recorded reason. That distinguishes a
            refused prompt from a provider outage or a timeout, which is worth knowing before you retype anything.
          </li>
        </ul>
        <Note>
          You only ever see your own requests here, and only the parts that concern you. Operational detail — the raw
          provider response, internal connection and trace identifiers — is kept to the administrator view.
        </Note>
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
          The paperclip opens an attach menu: upload a file, take a screenshot of a tab or window and crop it, or
          pick items from your Media library (project Media in a project chat). Files already in Media are attached by
          reference — they are not stored a second time.
        </p>
        <ul>
          <li>
            <strong>Images</strong> (for example <code>jpg</code>, <code>png</code>, <code>webp</code>, <code>gif</code>
            ) can be sent to vision-capable models.
          </li>
          <li>
            <strong>Video</strong> (for example <code>mp4</code>, <code>mov</code>, <code>mkv</code>, <code>webm</code>)
            and <strong>audio</strong> (for example <code>mp3</code>, <code>ogg</code>, <code>wav</code>,{" "}
            <code>m4a</code>) can be attached and play in the thread; the model receives a short note that the file was
            attached (not raw multimedia understanding unless your deployment adds that).
          </li>
          <li>
            <strong>Documents</strong> (PDF, Office, text, CSV, and similar) are processed for extractable text where
            supported.
          </li>
          <li>
            Executables, archives, HTML/SVG, and other blocked types stay unavailable. Oversized files and the
            per-message file count show an error before send (limits come from your administrator&apos;s Storage
            settings).
          </li>
          <li>
            In Private Mode, Media attach works for images, audio/video, and plain-text files, processed locally. Some
            Office/PDF types still need Private Mode off so the server can extract text.
          </li>
        </ul>
        <h3>Voice</h3>
        <ul>
          <li>Record or upload audio for transcription into the composer.</li>
          <li>
            Choose the voice recording language in Settings → General (Auto-detect, English or Persian) so
            transcription matches your speech; Auto-detect lets the model decide.
          </li>
          <li>The transcript lands in the composer as-is; edit it there before sending.</li>
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
          When an image-capable model (or image tool flow) is selected, Alpharouter generates images through the platform
          image API. Generation can continue in the background for that session; you can navigate away and return while
          a job is pending.
        </p>
        <ul>
          <li>Prompt enhancement / translation helpers may be available from the composer for image prompts.</li>
          <li>Completed images appear in the thread and usually in your Media library (unless Private mode).</li>
          <li>Costs count against your monthly budget like other paid requests.</li>
          <li>
            Some image models (for example OpenAI GPT Image) can take well over a minute. If the UI reports a gateway
            timeout, retry once and check Media — the image may still have finished on the server after the browser
            connection dropped.
          </li>
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
          <li>
            Optionally enable <strong>Generate audio</strong> when the selected video model supports soundtrack output.
          </li>
          <li>Completed videos appear in the thread and in your Media library (unless Private mode).</li>
          <li>Only one video job runs at a time per user by default; costs count against your monthly budget.</li>
          <li>
            A brief network hiccup while a clip renders no longer loses the job — the status check is retried. If a job
            does fail, the placeholder is replaced by the actual reason rather than a generic message, so you can tell
            a rejected prompt from a provider outage.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "chat-speech",
    title: "Text to speech",
    group: "Chat",
    content: (
      <>
        <h2>Text to speech</h2>
        <p>
          Enable <strong>Text to Speech</strong> in Chat Tools to turn your message text into spoken audio. Image and
          video generation tools are turned off while speech generation is on (and the reverse).
        </p>
        <ul>
          <li>Pick a voice and playback speed from the tools menu before sending.</li>
          <li>
            The platform generates audio from your message text (subject to a maximum character length shown in the
            tools menu).
          </li>
          <li>Completed audio appears in the thread and in your Media library (unless Private mode).</li>
          <li>Costs count against your monthly budget like other paid requests.</li>
        </ul>
        <Note>
          Voice <em>recording</em> (microphone → transcript into the composer) is separate from Text to Speech. See{" "}
          <a href="#chat-attachments">Attachments &amp; voice</a>.
        </Note>
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
          your deployment and model, and on what your administrator has granted your account: a tool you have not
          been given is not listed, and a chat that had it switched on before opens with it off.
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
              <td>
                Enables text-to-image and image-to-image flows from chat. See{" "}
                <a href="#chat-images">Image generation</a>.
              </td>
            </tr>
            <tr>
              <td>
                <strong>Video generation</strong>
              </td>
              <td>
                Creates clips from text or an attached image. See <a href="#chat-videos">Video generation</a>.
              </td>
            </tr>
            <tr>
              <td>
                <strong>Text to speech</strong>
              </td>
              <td>
                Generates spoken audio from your message text. See <a href="#chat-speech">Text to speech</a>.
              </td>
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
          IndexedDB. Alpharouter does <strong>not</strong> persist that session’s messages to the server.
        </p>
        <ul>
          <li>Enabling Private mode requires confirmation and is <strong>not reversible</strong> for that chat.</li>
          <li>Model calls still go through Alpharouter (and count toward budget) — only chat history storage is local.</li>
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
    id: "chat-memory",
    title: "Memory",
    group: "Chat",
    content: (
      <>
        <h2>Memory</h2>
        <p>
          Work profile and Memory are two additive context layers for non-private chats (they never replace session
          messages):
        </p>
        <ul>
          <li>
            <strong>Work profile</strong> — directory fields from your user record (Company, Department, Job title,
            Manager). Read-only in Settings → Work profile; managed by admins or directory sync.
          </li>
          <li>
            <strong>Automatic memory</strong> — durable facts learned from your non-private chats (preferences,
            constraints, health notes you discussed, recurring work context). Learning is silent. Manage it in Settings
            → Memory.
          </li>
        </ul>
        <ul>
          <li>
            <strong>Use my memories in chat</strong> (on by default) — inject relevant memories into new non-private
            turns.
          </li>
          <li>
            <strong>Automatically learn new things about me</strong> (on by default) — extract new facts after a
            conversation. Turn this off to stop learning while still using existing memories.
          </li>
          <li>
            <strong>Use my memories in apps with my API key</strong> (off by default) — your personal API key can be
            used from an editor, a script, or a service someone else runs. Turn this on only if you want those
            requests to receive your memories too. Nothing is ever learned from them either way.
          </li>
          <li>Private mode chats do not receive profile context or memories, and are never mined.</li>
          <li>
            You can disable, delete, or export memories. Deleting a fact also prevents it from being learned again
            from old chats, and that block survives a later delete-all.
          </li>
        </ul>
        <Note>
          Memories outlive individual chats. Prefer this for durable facts you are comfortable keeping on the server
          for your account.
        </Note>
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

  // ── Projects ──────────────────────────────────────────────────────────────
  {
    id: "user-projects",
    title: "Projects",
    group: "Projects",
    content: (
      <>
        <h2>Projects</h2>
        <p>
          Path: <code>/app/projects</code>. A project is a shared workspace: members, rooms, chats, files, and media
          belong to the project — not to one person&apos;s private Chat or Media library.
        </p>
        <h3>My projects and Explore</h3>
        <ul>
          <li>
            <strong>My projects</strong> lists workspaces you belong to. Archived and pending-deletion projects appear
            in their own sections so they stay out of the active list.
          </li>
          <li>
            <strong>Explore</strong> lists <em>public</em> projects visible to every signed-in user. Private projects
            never appear here.
          </li>
        </ul>
        <h3>Workspace tabs</h3>
        <p>
          Opening a project lands on <strong>Chats</strong>. Tabs from left to right:
        </p>
        <ul>
          <li>
            <strong>Chats</strong> — shared AI threads for this project.
          </li>
          <li>
            <strong>Rooms</strong> — member-only human discussion (hidden from public visitors who are not members).
          </li>
          <li>
            <strong>Resources</strong> — documents submitted for Knowledge review.
          </li>
          <li>
            <strong>Media</strong> — the project file library.
          </li>
          <li>
            <strong>Overview</strong> — member, chat, and file counts. Spend for the last 30 days is visible only to
            Owners, the Primary Owner, and reports admins.
          </li>
          <li>
            <strong>Activity</strong> — full spend and usage charts (Owners and Primary Owner only).
          </li>
          <li>
            <strong>Members</strong> then <strong>Settings</strong> — people, then project configuration.
          </li>
        </ul>
        <h3>Roles</h3>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Role</th>
              <th>What you can do</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Primary Owner</td>
              <td>
                The person who created the project. Same management as Owner, plus changing Owner
                access and archive, restore, delete, and purge. There is exactly one Primary Owner;
                they cannot leave or be demoted.
              </td>
            </tr>
            <tr>
              <td>Owner</td>
              <td>
                Manage members (Contributor and Viewer), settings, Activity, and project files. Cannot
                archive or delete the project, and cannot change another Owner&apos;s access. Extra
                Owners may leave.
              </td>
            </tr>
            <tr>
              <td>Contributor</td>
              <td>
                Rooms, Chat, upload resources and media, and edit project settings that Contributors are allowed to
                change. Cannot open Activity.
              </td>
            </tr>
            <tr>
              <td>Viewer</td>
              <td>Read rooms, chats, resources, and media. Viewers cannot send messages or change membership.</td>
            </tr>
          </tbody>
        </table>
        <h3>Rooms</h3>
        <p>
          <strong>Rooms</strong> are member-only human threads. There is no model, no tools, no Agent, and no AI spend.
          While you are on the Rooms tab, the AI chat sidebar is hidden so only the room list is on the left. Public
          visitors who are not project members do not see the Rooms tab. Room text is not copied into project memory and
          is not sent to the model.
        </p>
        <ul>
          <li>
            Owners and Contributors can create rooms, write, reply, and (for their own messages) edit or delete. Reply
            and the message actions use the same control style as Chat.
          </li>
          <li>
            Hover a room in the list to show the × control, then confirm — the same pattern as deleting a chat.
          </li>
          <li>
            Viewers can read rooms but cannot write, reply, or hand off to Chat.
          </li>
        </ul>
        <p>
          When a room reaches a decision, Owners and Contributors can use <strong>Send decision to Chat</strong>. Only
          the edited brief is placed in the new chat box so you can review it and press Send — it is not sent to the
          model automatically, and the full room transcript is not copied. The workspace then opens that new chat.
        </p>
        <h3>Shared chat</h3>
        <p>
          Project chats live under the workspace <strong>Chats</strong> tab. They are shared with members of that
          project. They are not copies of your personal <code>/app/chat</code> sessions, and Private Mode is not
          available in a project chat. Tools, model, and Agent in the composer are yours alone — other members of the
          same thread keep their own composer settings. Owners and Contributors can pin a thread for everyone in the project, and can
          copy a link with <code>?session=</code> to open that chat directly — even if it is older than the first page
          of the sidebar. Re-entering a project restores the last thread you had open. Pins and new messages appear for
          every member without a refresh. Each user prompt shows the sender&apos;s name. Making a project{" "}
          <strong>Public</strong> requires typing <code>PUBLIC</code>.
        </p>
        <h3>Activity</h3>
        <p>
          The Primary Owner and Owners can open the <strong>Activity</strong> tab in the workspace (or{" "}
          <code>/app/projects/&lt;id&gt;/activity</code>) to see spend, tokens, and charts for that project only.
          Contributors and Viewers do not have this tab.
        </p>
        <h3>Resources vs Media</h3>
        <ul>
          <li>
            <strong>Resources</strong> are documents submitted through the Knowledge pipeline (malware scan, text
            extraction, review). Owners and Contributors can upload up to 20 files at a time. Allowed types:{" "}
            <code>.pdf</code>, <code>.docx</code>, <code>.pptx</code>, <code>.xlsx</code>, <code>.txt</code>,{" "}
            <code>.md</code> / <code>.markdown</code>, <code>.html</code> / <code>.htm</code>, <code>.csv</code>,{" "}
            <code>.json</code>. Until a file is <strong>Published</strong>, members see{" "}
            <strong>Waiting for Admin Approval</strong>. After an admin publishes the version, project chat may inject
            short excerpts from that file when Settings allows it (Owners: <strong>Use project resources</strong>). That
            is not the same as Agent Knowledge retrieval: publishing a Knowledge <em>release</em> and building the vector
            index is for Agents bound to that Knowledge Base, not for ordinary project chat.
          </li>
          <li>
            <strong>Media</strong> are binary files (images, video, audio, uploads) stored in the project library.
            Images, video, audio, and other files generated or attached in a project chat are stored here (not in your
            personal Media library) so every member can open them. If the project is over quota, the file is kept only
            for the sender.
          </li>
        </ul>
        <h3>Memory and grounding</h3>
        <p>
          Owners can add short project memory facts in Settings and optionally allow granted memory from other projects.
          Room messages never become memory. Resource excerpts and memory are injected only into AI chats of this
          project — never into Rooms, and never into your personal <code>/app/chat</code> sessions.
        </p>
        <h4>Automatic project memory</h4>
        <p>
          With <strong>Automatically learn from project chats</strong> enabled in Settings, the assistant quietly keeps
          durable team facts it picks up from the project's AI chats — decisions, conventions, the stack, deadlines,
          responsibilities, client constraints — and reuses them in later turns so you do not have to repeat them.
        </p>
        <ul>
          <li>
            Learned facts belong to the <strong>project</strong>, not to you: every member sees them, and each fact
            records who contributed it and which chat it came from.
          </li>
          <li>
            Only the AI chat tab is mined. Rooms, private chats, and your personal chats outside the project are never
            read.
          </li>
          <li>
            Personal and sensitive details — health, finances, and private facts about individuals — are dropped and
            never stored as project memory, even if they were mentioned in the chat.
          </li>
          <li>
            Your <strong>personal</strong> memory is never used inside a project chat, and a project chat never adds
            anything to it. The two are fully separated.
          </li>
          <li>
            In Settings, Owners can filter Manual vs Learned facts, disable or delete a single fact, or use{" "}
            <strong>Delete all learned facts</strong> to clear everything the assistant learned while keeping
            hand-written facts. A deleted fact is not learned again from the same chats.
          </li>
        </ul>
        <h3>Invitations</h3>
        <p>
          The Primary Owner and Owners create a link (Contributor or Viewer only — never Owner or Primary Owner). Share
          the link, or optionally email it to an existing Alpharouter user when SMTP is configured. If email is
          unavailable, the invitation is still created: copy the link from the dialog. Claim invitations at{" "}
          <code>/app/projects/invite</code>.
        </p>
        <Note>
          Personal Chat and personal Media stay private to you. Project content is visible to project members according
          to their role.
        </Note>
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
          (images, video, audio, and documents; non-private).
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
          The same tabbed Activity experience administrators use is scoped to <strong>you</strong>: there is no user
          filter and no organization-wide “top users” view.
        </p>
        <h3>Tabs</h3>
        <ul>
          <li>
            <strong>Overview</strong> — KPIs, usage and token charts, request heatmap, and breakdowns by model and app.
          </li>
          <li>
            <strong>Trends</strong> — how your models and apps change over the selected period.
          </li>
          <li>
            <strong>Explore</strong> — pick metric, grouping, rollup, and chart type; export a PDF snapshot.
          </li>
        </ul>
        <h3>Toolbar</h3>
        <ul>
          <li>Period, timezone, filters (model, app, status), group-by, CSV/PDF export.</li>
        </ul>
        <p>
          Your monthly budget remaining is also visible from the profile menu. Organization-wide dashboards and gateway
          API key analytics are administrator-only.
        </p>
        <Note>
          If your administrator assigns you a <strong>gateway API key</strong> for an external tool (scripts, IDEs,
          Kilo Code), that key&apos;s spend is tracked against the key&apos;s credit pool — not your personal monthly
          budget. Your Activity page still shows requests attributed to your user when the key owner is you. Traffic from
          your <strong>personal API key</strong> (Settings → API Key) appears in Activity and admin logs with your key
          name.
        </Note>
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
        <p>Open Settings from the profile menu:</p>
        <h3>General</h3>
        <ul>
          <li>Time zone for activity displays</li>
          <li>Voice recording language (English / Persian)</li>
          <li>
            Chat notification — optional toast (and sound) when a chat finishes while you are in another chat or the
            tab is in the background
          </li>
          <li>Theme: light, dark, or system</li>
        </ul>
        <h3>Work profile</h3>
        <ul>
          <li>
            View read-only directory fields (Company, Department, Job title, Manager) used in non-private chats
          </li>
        </ul>
        <h3>Memory</h3>
        <ul>
          <li>Toggle whether memories are referenced in non-private chats (default on)</li>
          <li>Toggle whether new facts are learned automatically (default on)</li>
          <li>Review, disable, delete, or export learned memories; delete-all asks for three confirmations</li>
        </ul>
        <h3>Data Control</h3>
        <ul>
          <li>
            <strong>Export</strong> server-side chats as JSON
          </li>
          <li>
            <strong>Import</strong> JSON from Alpharouter, ChatGPT, or Open WebUI formats (merges into your account)
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
        <h3>API Key</h3>
        <p>
          Create one <strong>personal API key</strong> for OpenAI-compatible tools (scripts, IDEs, Kilo Code). Usage debits your monthly budget (same
          pool as Chat). Revoke permanently from Settings when rotating credentials; create a new key only after
          revoking the old one.
        </p>
        <ul>
          <li>Base URL: your Alpharouter <code>/v1</code> endpoint (shown after creation).</li>
          <li>Header: <code>Authorization: Bearer &lt;your-key&gt;</code></li>
          <li>
            The plaintext key is shown once at creation and is stored only as a hash, so nobody — not an
            administrator, not the database — can read it back. Copy it into a password manager before closing the
            dialog; if it is lost, the only way forward is to revoke it and update every tool that used it.
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
            <strong>Budget</strong> — monthly USD allowance from your plan. Chat, images, tools, and your{" "}
            <strong>personal API key</strong> (Settings → API Key) consume it.
            Separate <strong>gateway API keys</strong> issued by administrators use their own credit pool.
          </li>
          <li>
            <strong>Budget warnings</strong> — a notification appears once when you pass{" "}
            <strong>70%</strong> of your monthly budget, and again at <strong>90%</strong>. Each level is shown
            once per month, and the figure counts spend already committed to requests still running, so it matches
            the number in this menu. A single expensive request that jumps straight past both lines shows only the
            90% warning. If an administrator raises your plan or resets your usage, the warnings can appear again
            later in the same month. Once you reach 100% requests are refused (HTTP 402) until the next month or a
            plan change.
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
    title: "Copyright & licensing",
    group: "Legal",
    content: (
      <>
        <h2>Copyright &amp; licensing</h2>
        <p>Copyright © 2026 {TRADEMARK_OWNER}.</p>

        <h3>The source code</h3>
        <p>
          {PRODUCT_NAME_MARKED} is licensed under the MIT License; the full text ships as <code>LICENSE</code> in the
          repository and is the authoritative version. Use, modification and redistribution are permitted, commercially
          included. If you redistribute {PRODUCT_NAME_MARKED} — modified or not, as source or inside an image — keep the
          copyright notice and the licence text with it. That is the whole obligation.
        </p>
        <p>
          The name and the logos are not part of it. They are licensed separately; see{" "}
          <a href="#trademarks">Trademarks</a>.
        </p>

        <h3>Third-party components</h3>
        <p>
          A deployment runs software {PRODUCT_NAME_MARKED} neither owns nor relicenses: PostgreSQL, Redis, Qdrant,
          SeaweedFS, nginx, ClamAV, and the Python and JavaScript dependencies declared in <code>requirements.txt</code>{" "}
          and <code>package.json</code>. Each keeps its own licence and some are copyleft — ClamAV is GPL.
        </p>
        <p>
          They run as their own processes and containers rather than being linked into {PRODUCT_NAME_MARKED}, so
          operating the stack puts no licence obligation on code you write against it. Redistributing a modified build
          of one of those components is governed by that component&apos;s licence, not by this one.
        </p>

        <h3>Your data, and what the models produce</h3>
        <p>
          Prompts, uploaded documents, and the images, video and audio generated through the platform belong to your
          organization. {PRODUCT_NAME_MARKED} claims nothing in them and sends nothing anywhere except to the providers
          you configure.
        </p>
        <p>
          What a given model may be asked to produce, and how its output may be used, is governed by your agreement
          with that provider. {PRODUCT_NAME_MARKED} routes the request and records the cost; it does not grant those
          rights and cannot widen them.
        </p>

        <p>
          Contact: <a href="mailto:Majid.Arasskhani@gmail.com">Majid.Arasskhani@gmail.com</a>
        </p>
        <Note>
          This section describes the licence in plain terms. It is a summary, not legal advice, and{" "}
          <code>LICENSE</code> and <code>TRADEMARK.md</code> govern where they differ.
        </Note>
      </>
    ),
  },
  {
    id: "trademarks",
    title: "Trademarks",
    group: "Legal",
    content: (
      <>
        <h2>Trademarks</h2>
        <p>
          {PRODUCT_NAME_MARKED}, Alpha Router, AlphaRouter and the product logos (the <strong>Marks</strong>) are
          trademarks of {TRADEMARK_OWNER}. The MIT License covers the source code only and grants no right to the
          Marks. <code>TRADEMARK.md</code> in the repository is the policy of record; this is the short version.
        </p>
        <h3>Running it, and talking about it</h3>
        <p>
          Deploying {PRODUCT_NAME_MARKED} inside your organization needs no permission and no branding change. You may
          say you run it, that a tool is compatible with it, or that something is based on it, and you may name it in
          documentation, reviews and academic work — as long as the statement is accurate and does not imply the
          project endorses you.
        </p>
        <h3>Forking it</h3>
        <p>
          <strong>A fork you publish has to carry its own name and its own visual identity</strong> — the Marks stay
          with this project and are not yours to take. That covers a variant as much as a copy: a changed spelling,
          an added or dropped word, a translation, a recoloured or redrawn logo, a lockup that keeps the letter-A
          mark. A name that is confusingly similar is the same infringement as the name itself. The same rule applies
          to naming a distribution, a hosted service or a competing product, and to registering a domain, social
          handle, package name or organization that suggests an official project.
        </p>
        <p>
          <strong>Renaming it does not make it yours.</strong> Changing the branding is a licensing requirement, not a
          transfer of authorship: the copyright notice and the licence text travel with the code whether or not the
          name goes with them, and that is the one obligation MIT imposes. So a fork may not present{" "}
          {PRODUCT_NAME_MARKED} as its own original work, strip the attribution in order to do so, or describe itself
          as written from scratch. Naming the project it derives from is expected and permitted; erasing it is not.
        </p>
        <p>
          The mirror image is equally out: shipping a modified build that still looks like the official product, or
          removing the Marks so a modified build can be passed off as the official release.
        </p>
        <Note>
          Rebranding a fork is a licensing requirement, not a courtesy — and it is also what keeps your users from
          filing your bugs against this project. For an official partnership or an approved distribution, ask:{" "}
          <a href="mailto:Majid.Arasskhani@gmail.com">Majid.Arasskhani@gmail.com</a>.
        </Note>
      </>
    ),
  },
];
