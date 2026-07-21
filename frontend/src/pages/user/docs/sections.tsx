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
  {
    id: "introduction",
    title: "Introduction",
    group: "Get started",
    content: (
      <>
        <h1>User Manual</h1>
        <p className="docs-lead">
          This guide explains how to use Alpha Router as an end user: chat with enabled AI models, manage your media files,
          review model recommendations, and track your usage and spend. Administrators configure models, budgets, roles,
          and policies; this manual focuses on what you can do in the <strong>/app</strong> panel after you sign in.
        </p>
        <p>
          The left sidebar gives quick access to <strong>Chat</strong>, <strong>Media</strong>,{" "}
          <strong>Recommendations</strong>, <strong>My Usage &amp; Activity</strong>, and this manual. Your profile menu
          (top right) shows your monthly <strong>Budget</strong>, theme toggle, and sign out. If you also hold admin
          roles, an <strong>Administration</strong> link opens your admin panel.
        </p>
        <div className="docs-cards">
          <div className="docs-card">
            <h3>Chat</h3>
            <p>Multi-session chat with attachments, tools (including code interpreter), voice, image generation, composer translation (To ENG), a prompt queue, per-session composer drafts, and a scroll-to-bottom control in long threads.</p>
          </div>
          <div className="docs-card">
            <h3>Media</h3>
            <p>Files you upload or generate in chat, with search, filters, and optional scheduled cleanup.</p>
          </div>
          <div className="docs-card">
            <h3>Recommendations</h3>
            <p>Personalized model suggestions based on how you use Alpha Router — quality fit and value picks for your workload.</p>
          </div>
          <div className="docs-card">
            <h3>My Usage &amp; Activity</h3>
            <p>Personal spend, tokens, heatmaps, top models, and export to CSV or PDF.</p>
          </div>
        </div>
      </>
    ),
  },
  {
    id: "why-alpha-router",
    title: "Why Alpha Router exists",
    group: "Get started",
    content: (
      <>
        <h2>Why Alpha Router exists</h2>
        <p>
          Organizations need one place to offer AI to employees without giving everyone direct access to provider API
          keys or uncontrolled spend. Alpha Router is that platform: your company runs it, assigns you a budget, and exposes
          only approved models through a built-in web app (and optionally an OpenAI-compatible <code>/v1</code> API).
        </p>
        <p>As a user, Alpha Router gives you:</p>
        <ul>
          <li>
            <strong>One sign-in</strong> — local account, LDAP/Active Directory, or SSO (Keycloak), depending on what
            your admin configured.
          </li>
          <li>
            <strong>Monthly budget</strong> — a USD allowance from your plan; usage in chat and any personal API keys
            counts against it.
          </li>
          <li>
            <strong>Curated models</strong> — only models your administrator enabled appear in the model picker.
          </li>
          <li>
            <strong>Private workspace</strong> — your chats, media, and activity history are scoped to your account.
          </li>
          <li>
            <strong>Transparency</strong> — see what you spent, which models you used, and export reports for your own
            records.
          </li>
        </ul>
        <Note>
          Alpha Router can also expose an optional organizational AI gateway (<code>/v1</code>) for external tools (for example
          Open WebUI). That setup is managed by administrators; most day-to-day work happens in this web app.
        </Note>
      </>
    ),
  },
  {
    id: "alpha-router-documentation",
    title: "Alpha Router documentation",
    group: "Get started",
    content: (
      <>
        <h2>Alpha Router documentation</h2>
        <p>This User Manual is organized as follows:</p>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Section</th>
              <th>What it covers</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <strong>Chat</strong>
              </td>
              <td>Sessions, folders, <strong>Chat Tools</strong>, attachments, voice, streaming, prompt queue, composer drafts, scroll-to-bottom, and read-only mode.</td>
            </tr>
            <tr>
              <td>
                <strong>Chat Tools</strong>
              </td>
              <td>Web Search, Web Fetch, Image Generation, Code Interpreter, Private Mode, Reset defaults (no Chat Memory). Composer bar also has <strong>To ENG</strong> (globe icon; translate draft to English).</td>
            </tr>
            <tr>
              <td>
                <strong>Media</strong>
              </td>
              <td>Your file library, quota, views, download, delete, and retention schedule.</td>
            </tr>
            <tr>
              <td>
                <strong>Recommendations</strong>
              </td>
              <td>Usage-based model suggestions — quality fit scores and value picks for your token mix.</td>
            </tr>
            <tr>
              <td>
                <strong>My Usage &amp; Activity</strong>
              </td>
              <td>Metrics, heatmap, period filters, exports, and how spend relates to your budget.</td>
            </tr>
            <tr>
              <td>
                <strong>Profile &amp; account</strong>
              </td>
              <td>Budget display, theme, Administration link (for admins), and deactivated (read-only) accounts.</td>
            </tr>
          </tbody>
        </table>
        <p>
          Administrators have a separate <strong>Admin Guide</strong> in the admin panel (Developer → Admin Guide) for
          connections, users, LDAP sync, scoped roles, retention policy, database scaling (<code>.env</code> / PgBouncer),
          and optional platform API setup.
        </p>
      </>
    ),
  },
  {
    id: "user-chat",
    title: "Chat",
    group: "Features",
    content: (
      <>
        <h2>Chat</h2>
        <p>
          Open <strong>Chat</strong> from the sidebar. The layout has a left column for history and a main area for
          messages. On chat pages the sidebar can slide in from the left edge when you move the mouse to the menu rail.
        </p>

        <h3>Chat sidebar — Chats tab</h3>
        <ul>
          <li>
            <strong>New chat</strong> — starts a fresh session with all tools off.
          </li>
          <li>
            <strong>Search</strong> — hybrid search: filters loaded sessions instantly; after 2+ characters and a short
            pause, also searches titles on the server. Message-body search is available when your query matches stored
            text (subject to per-account rate limits).
          </li>
          <li>
            <strong>Scroll</strong> — the chat list loads more sessions as you scroll down (virtualized for performance
            with long histories).
          </li>
          <li>
            <strong>Folders</strong> — create, rename, recolor, and delete folders; drag chats between folders.
          </li>
          <li>
            <strong>Session menu</strong> — rename, delete, or move a chat.
          </li>
          <li>
            <strong>Persistence</strong> — non-private chats sync to your account on the server (PostgreSQL). The sidebar
            loads your session list in pages; opening a chat loads the latest messages first; scroll up in the thread
            for older ones. Previously opened chats are cached in your browser to make switching faster. You can continue
            from another browser after sign-in. <strong>Private Mode</strong> keeps a chat in the browser only (localStorage
            + IndexedDB) — see Chat Tools below.
          </li>
          <li>
            <strong>Multiple tabs</strong> — if you open Alpha Router in several tabs, they stay in sync via lightweight refresh.
            Any tab can send messages and save chats; only one tab at a time syncs <strong>folder</strong> changes to the
            server. The <strong>prompt queue</strong> lives in each tab separately — queuing in tab A does not appear in
            tab B. Avoid editing the same chat in two tabs at the exact same moment.
          </li>
        </ul>

        <h3>Chat sidebar — Media tab</h3>
        <p>
          Quick view of media linked from chat (same files as the full <strong>Media</strong> page). Re-uploading an
          identical file reuses the same stored blob (content hash) and moves the item to the top.
        </p>

        <h3>Model picker</h3>
        <ul>
          <li>Choose any <strong>enabled</strong> model your administrator exposed.</li>
          <li>
            Use the <strong>checkmark</strong> control beside a model to set your <strong>default model</strong> for new
            chats. The choice is saved to your account and survives page refresh and sign-in on another browser.
          </li>
        </ul>

        <h3 id="user-chat-tools">Chat Tools</h3>
        <p>
          Open the <strong>Tools</strong> menu in the message composer (next to the model picker). The panel title is{" "}
          <strong>Chat Tools</strong>. Each option has a toggle; a badge on the Tools button shows how many server tools
          are currently on. New chats start with every tool <strong>off</strong>.
        </p>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Tool</th>
              <th>Subtitle in UI</th>
              <th>What it does</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <strong>Web Search</strong>
              </td>
              <td>Fresh web results</td>
              <td>
                Lets the assistant search the public web for up-to-date information before answering. Turn on when you
                need current events, prices, or facts that may not be in the model&apos;s training data. Uses your
                monthly budget like any other chat request.
              </td>
            </tr>
            <tr>
              <td>
                <strong>Web Fetch</strong>
              </td>
              <td>Read links in your message</td>
              <td>
                When your message contains URLs, Alpha Router can fetch and read those pages so the model can summarize or
                answer questions about them. Paste the link in the same message as your question.
              </td>
            </tr>
            <tr>
              <td>
                <strong>Image Generation</strong>
              </td>
              <td>Create or edit images from chat</td>
              <td>
                Generates images from text prompts, or edits an attached image when you add a photo and describe
                the change. Requires an <strong>image-capable</strong> model (text-to-image and/or image-to-image).
                Choose an <strong>aspect ratio</strong> preset (1:1, 16:9, 9:16, 3:2, 2:3, or Custom W:H) in Chat Tools;
                image-to-image output matches the source attachment size. Long runs may continue in the background while
                you switch chats. Generated images normally appear in <strong>Media</strong> unless Private Mode is on.
              </td>
            </tr>
            <tr>
              <td>
                <strong>Code Interpreter</strong>
              </td>
              <td>Run Python on data &amp; math</td>
              <td>
                Lets the assistant run <strong>Python</strong> in a sandbox when it writes a <code>```python</code>{" "}
                block.                 Useful for spreadsheets, CSV analysis, calculations, and parsing. Attachment text (for example
                extracted PDF/CSV content) is available in the sandbox by filename. Output appears under{" "}
                <strong>Code output</strong> in the chat. Python and output blocks show a toolbar with{" "}
                <strong>Copy</strong> and <strong>Expand/Collapse</strong> at the <strong>top and bottom</strong> so you
                can act on long code without scrolling back up. Counts toward your monthly budget like other chat requests.
              </td>
            </tr>
            <tr>
              <td>
                <strong>Private Mode</strong>
              </td>
              <td>Store this chat and its media on this device only</td>
              <td>
                Applies to the <strong>current chat only</strong>. Messages and media stay in this browser only — not on
                the Alpha Router server. Chat metadata is stored in <strong>localStorage</strong>; images and image attachments
                are stored in <strong>IndexedDB</strong> on this device. They will <strong>not</strong> sync to other
                devices and will <strong>not</strong> appear in the server-side Media library. Image generation (text-to-image
                and image-to-image) works in Private Mode; results stay local. Data may be lost if you clear browser site
                data. Enabling shows a confirmation dialog (above the Tools menu); turning off uploads local media to the
                server when possible. Chats in Private Mode show the same lock icon in the sidebar and at the top of the
                chat panel.
              </td>
            </tr>
          </tbody>
        </table>
        <p>
          <strong>Reset defaults</strong> at the bottom of the Chat Tools panel turns off Web Search, Web Fetch,
          Image Generation, and Code Interpreter for the current chat. It does <strong>not</strong> change Private Mode — disable that
          separately if needed.
        </p>
        <Note>
          Chat Tools settings are saved <strong>per chat session</strong>. Turning on Web Search in one chat does not
          enable it in another. Private Mode is also per chat. <strong>Chat Memory</strong> (cross-session recall) is{" "}
          <strong>not</strong> part of Alpha Router — context is limited to the messages in the current chat thread.
        </Note>

        <h3>Scrolling older messages</h3>
        <p>
          Long conversations load the most recent messages first. Scroll to the top of the message area to load earlier
          turns. Very old messages may no longer be available if your organization enforces chat retention.
        </p>
        <p>
          When you scroll up in a long thread, a <strong>down-arrow</strong> button appears above the composer. Click it
          to jump smoothly back to the latest messages. It hides automatically when you are already near the bottom.
        </p>

        <h3>Chat history retention</h3>
        <p>
          Your organization&apos;s Super Admin may enable a global chat retention policy on the admin{" "}
          <strong>Retention Policy</strong> page. When enabled, messages older than the configured number of days can be
          removed automatically on a schedule or when an admin runs a manual purge. Sessions that lose all messages during
          a purge are removed from your chat list. Export important conversations if your org uses retention.
        </p>

        <h3>Search &amp; rate limits</h3>
        <p>
          Chat search is optimized for large histories: local filtering plus server-side title search. If you search very
          frequently you may briefly see a rate-limit message — wait a moment and try again. Limits apply per account,
          not per browser tab.
        </p>

        <h3>Composer — send, queue, and stop</h3>
        <ul>
          <li>
            <strong>Send</strong> — type in the box and press Enter or click the send arrow. Your message appears in the
            thread right away; the assistant reply streams below it.
          </li>
          <li>
            <strong>Composer drafts</strong> — text and pending attachments are remembered <strong>per chat</strong> while
            you switch between sessions in the same browser tab. Drafts are <strong>not</strong> saved across a full page
            refresh or browser restart.
          </li>
          <li>
            <strong>To ENG</strong> — globe icon in the composer bar (next to Tools). Translates the current draft in the
            text box to fluent English without adding new details. Shows a spinner while translating. Disabled when the box
            is empty or the text is already English. Replaces the composer text so you can review before sending. Uses your
            monthly budget like a small chat request.
          </li>
          <li>
            <strong>Prompt queue</strong> — if you send another message while the assistant is still generating, it is
            added to a numbered queue above the composer instead of interrupting the current reply. Your queued message
            appears in the queue immediately. When the current reply finishes, queued messages are sent{" "}
            <strong>automatically, one at a time, in order</strong> (including after image generation completes). Use ✎
            to edit a queued item (it returns to the composer) or × to remove it.
          </li>
          <li>
            <strong>Stop (■)</strong> — appears while the model is generating. Click it to cancel the active reply in this
            tab. Messages still waiting in the queue will be sent afterward unless you remove them.
          </li>
        </ul>

        <h3>Attachments &amp; voice</h3>
        <ul>
          <li>
            <strong>Files</strong> — PDFs and documents: text is extracted server-side; images use vision when the
            model supports it. Limits apply per message. Attachments are kept when a message is queued.
          </li>
          <li>
            <strong>Voice</strong> — record from the microphone; the transcript is sent as your message (browser
            speech recognition).
          </li>
        </ul>

        <h3>Messages</h3>
        <ul>
          <li>Your message appears immediately; the assistant reply <strong>streams</strong> token by token.</li>
          <li>Switching chats does not mix streams from another session.</li>
          <li>
            <strong>Refresh during a reply</strong> — if you reload the page while the model is still writing, live
            streaming in the browser stops (this is normal). Sign in again and open the same chat; Alpha Router polls the server
            and shows the completed reply when it is ready.
          </li>
          <li>
            <strong>Info icon</strong> on each message — hover to see timestamps: when you sent a prompt and when the
            assistant response was received (when recorded).
          </li>
          <li>Copy assistant replies from the message action menu where available.</li>
        </ul>

        <h3>Budget</h3>
        <p>
          Each chat request consumes from your monthly USD budget. If you exceed it, new requests are blocked until the
          next calendar month or an administrator adjusts your plan. Check remaining budget in the profile menu (
          <code>used / total $</code>).
        </p>

        <Warn>
          Alpha Router can make mistakes. Verify important facts before acting on model output.
        </Warn>
      </>
    ),
  },
  {
    id: "user-chat-tools",
    title: "Chat Tools",
    group: "Features",
    content: (
      <>
        <h2>Chat Tools</h2>
        <p>
          In the chat composer, click <strong>Tools</strong> to open the <strong>Chat Tools</strong> panel. Use toggles
          to enable features for the <strong>current chat only</strong>. See also the Chat section for sessions,
          folders, and attachments.
        </p>
        <h3>Web Search</h3>
        <p>
          <em>Fresh web results.</em> The assistant can query the live web before replying — useful for news, prices, or
          anything that changes over time. Counts toward your monthly budget.
        </p>
        <h3>Web Fetch</h3>
        <p>
          <em>Read links in your message.</em> Include one or more URLs in your prompt; Alpha Router fetches page content so the
          model can summarize or answer about those pages.
        </p>
        <h3>Image Generation</h3>
        <p>
          <em>Create or edit images from chat.</em> With Image Generation on, the model picker lists{" "}
          <strong>Auto Router</strong> plus every enabled <strong>text-to-image</strong> and{" "}
          <strong>image-to-image</strong> model — pick a specific model anytime.
        </p>
        <ul>
          <li>
            <strong>Text to image</strong> — describe what you want in the message (no attachment required). Pick an{" "}
            <strong>aspect ratio</strong> in Chat Tools: Square (1:1), Wide (16:9), Tall (9:16), Landscape (3:2),
            Portrait (2:3), or Custom (W:H such as 21:9). You can also override in the prompt with{" "}
            <code>--ar 16:9</code>.
          </li>
          <li>
            <strong>Image to image</strong> — attach a photo, then describe how to change it (e.g. style, background,
            objects). Output size matches the source image. Use a model that supports image input (e.g. Gemini image or
            FLUX Kontext).
          </li>
          <li>
            <strong>Regenerate</strong> — reuses the same prompt, aspect ratio, and reference image when applicable.
          </li>
        </ul>
        <p>
          Images are saved to your Media library unless Private Mode is enabled for that chat.
        </p>
        <h3>Translate to English (To ENG)</h3>
        <p>
          Click <strong>To ENG</strong> (globe icon) in the composer bar to translate your draft to fluent English. A
          spinner replaces the icon while translation runs. The result replaces the text in the box — nothing is sent until
          you press Send. Works for text chat and image prompts alike. Alpha Router keeps your original wording when the model
          would change too much. Counts toward your monthly budget like a small chat request.
        </p>
        <h3>Code Interpreter</h3>
        <p>
          <em>Run Python on data &amp; math.</em> Turn this on when you want the model to execute Python—not just show
          code— for analysis, charts data, or working with uploaded documents.
        </p>
        <h4>How it works</h4>
        <ol>
          <li>
            Enable <strong>Code Interpreter</strong> in Chat Tools for the current chat.
          </li>
          <li>
            Ask a question that needs computation (for example “summarize this CSV” or “calculate the average”).
          </li>
          <li>
            The model may reply with a <code>```python</code> fenced block. Alpha Router runs the <strong>last</strong> Python
            block automatically in a sandbox and injects the result back into the conversation.
          </li>
          <li>
            Look for <strong>Code output</strong> below the assistant message (stdout/stderr from the run).
          </li>
          <li>
            Use <strong>Copy</strong> or <strong>Expand/Collapse</strong> on the code block toolbar at the top{" "}
            <strong>or bottom</strong> — helpful when a long <code>```python</code> block or output log extends below the
            fold.
          </li>
        </ol>
        <h4>What you can use</h4>
        <ul>
          <li>
            Standard library modules such as <code>json</code>, <code>math</code>, <code>statistics</code>,{" "}
            <code>re</code>, <code>csv</code>, <code>datetime</code>, and <strong>pandas</strong> when installed.
          </li>
          <li>
            <strong>Attachments</strong> — text extracted from documents in your message is placed in the sandbox under
            the original filename (for example <code>report.csv</code>). Reference that name in Python.
          </li>
        </ul>
        <h4>Limits &amp; safety</h4>
        <ul>
          <li>
            Each run has a <strong>20 second</strong> timeout; very large outputs are truncated.
          </li>
          <li>
            Dangerous imports (network, subprocess, filesystem outside the temp workspace, etc.) are blocked.
          </li>
          <li>
            Up to <strong>3</strong> execute-and-continue rounds per assistant turn when the model keeps refining code.
          </li>
          <li>
            Code runs on the Alpha Router server, not in your browser. Do not paste secrets into prompts when this tool is on.
          </li>
        </ul>
        <Note>
          Code Interpreter is independent of Image Generation and Web Search—you can combine tools, but each enabled
          tool may add latency and budget usage. <strong>Chat Memory</strong> is not available; the model only sees this
          chat&apos;s message history.
        </Note>
        <h3>Private Mode</h3>
        <p>
          <em>Store this chat and its media on this device only.</em> Nothing from this session is written to the Alpha Router
          server while Private Mode is on: no server sync, no Media library entries, no access from other browsers.
          Confirm when enabling (the dialog appears in front of the Tools menu). To disable, Alpha Router tries to upload local
          media to the server first. The same lock icon appears in the sidebar and at the top of the chat panel.
        </p>
        <h4>What stays local</h4>
        <ul>
          <li>
            <strong>Chat text &amp; settings</strong> — stored in browser <strong>localStorage</strong> (per signed-in
            user).
          </li>
          <li>
            <strong>Generated images &amp; image attachments</strong> — stored as blobs in browser{" "}
            <strong>IndexedDB</strong> (<code>alpha_router_private_media</code>); message JSON holds small references only.
          </li>
          <li>
            <strong>Image generation</strong> — text-to-image and image-to-image both work; the API is called with{" "}
            <code>persist: false</code> so images are not saved on the server.
          </li>
        </ul>
        <h3>Reset defaults</h3>
        <p>
          Turns off Web Search, Web Fetch, Image Generation, and Code Interpreter. Does not affect Private Mode.
        </p>
        <Warn>
          Private chats may be lost if you clear site data or use a different browser. Do not rely on Private Mode for
          long-term archival. If browser storage fills up, you may see a save error — delete old private chats or clear
          site data for this site.
        </Warn>
      </>
    ),
  },
  {
    id: "user-media",
    title: "Media",
    group: "Features",
    content: (
      <>
        <h2>Media (storage)</h2>
        <p>
          The <strong>Media</strong> page lists every file you attached or generated in chat (except content kept in{" "}
          <strong>Private Mode</strong> on this device only). Files are stored on the organization&apos;s Alpha Router server
          in object storage; the UI loads them through your signed-in session—other users cannot see your library.
        </p>

        <h3>Persistence &amp; Private Mode</h3>
        <p>
          Normally, files you upload or generate in chat are saved on the server and listed here. Identical file content
          is stored once per account (deduplicated by content hash) but still appears in your Media list. If you use{" "}
          <strong>Private Mode</strong> in Chat Tools for a session, that chat&apos;s media stays in your browser only
          (IndexedDB for image blobs; localStorage for chat metadata) and will not appear in this library until you turn
          Private Mode off and migration succeeds.
        </p>

        <h3>Browsing</h3>
        <ul>
          <li>
            <strong>Search</strong> — filter by filename.
          </li>
          <li>
            <strong>Date range</strong> — <em>From</em> / <em>To</em> filters narrow the list.
          </li>
          <li>
            <strong>View modes</strong> — grid or list; your preference is remembered in the browser.
          </li>
          <li>
            Click a preview to open or download; images show inline thumbnails.
          </li>
        </ul>

        <h3>Quota</h3>
        <p>
          A quota bar shows how much of your allowed storage you use. Super Admins set the global per-user limit (1–100 GB)
          on <strong>Storage Management</strong> in the admin panel; the default is 1 GB until changed. If you approach the
          limit, delete old files or ask an admin to raise the quota or adjust retention settings.
        </p>

        <h3>Actions</h3>
        <ul>
          <li>
            <strong>Select</strong> multiple items and delete in bulk.
          </li>
          <li>
            <strong>Download ZIP</strong> — export selected files as an archive.
          </li>
          <li>
            Row menu — download or delete individual files.
          </li>
        </ul>

        <h3>Scheduled cleanup</h3>
        <p>
          You can configure a personal retention schedule (when allowed): keep files for N days and optionally run
          automatic cleanup at a daily time. Administrators may also enforce global media retention and scheduled purge
          from the admin <strong>Retention Policy</strong> page.
        </p>

        <Warn>
          If an administrator runs <strong>DELETE ALL MEDIA</strong> on <strong>Storage Management</strong>, all
          organization media blobs are deleted. Your chat text may remain, but images and attachments in older messages
          may stop loading until you upload them again.
        </Warn>

        <Note>
          Deleting media removes your library entry. The underlying blob may remain in object storage until no user
          reference needs it and retention policy allows cleanup.
        </Note>
      </>
    ),
  },
  {
    id: "user-recommendations",
    title: "Recommendations",
    group: "Features",
    content: (
      <>
        <h2>Recommendations</h2>
        <p>
          Open <strong>Recommendations</strong> from the sidebar (<code>/app/recommendations</code>). Alpha Router analyzes your
          recent usage — dominant request types, token mix, and primary models — and suggests alternatives from the
          enabled catalog.
        </p>
        <h3>What you see</h3>
        <ul>
          <li>
            <strong>Quality</strong> — models that fit your usage pattern (tier, context length, and workload type).
          </li>
          <li>
            <strong>Value</strong> — models with similar capability at lower estimated cost for your token mix.
          </li>
          <li>
            <strong>Period toolbar</strong> — preset ranges (7, 30, 90 days) or a custom date range.
          </li>
        </ul>
        <p>
          Match scores are guidance based on catalog metadata and your activity — not measured output quality. If you
          have little or no usage in the selected period, picks fall back to generally suitable enabled models.
        </p>
        <p>
          Use recommendations to discover models before starting a new chat; switch models from the Chat model picker
          when you want to try a suggestion.
        </p>
      </>
    ),
  },
  {
    id: "user-activity",
    title: "My Usage & Activity",
    group: "Features",
    content: (
      <>
        <h2>My Usage & Activity</h2>
        <p>
          This page is your personal analytics dashboard: how much you spent, which models you used, and how activity
          changed over time. It uses the same period and timezone controls as the admin activity views, scoped only to
          your account.
        </p>

        <h3>Header controls</h3>
        <ul>
          <li>
            <strong>Period</strong> — Today, Yesterday, This week, Past 7/30 days, This month, etc.
          </li>
          <li>
            <strong>Timezone</strong> — Local time or UTC for charts and heatmaps.
          </li>
          <li>
            <strong>Settings (gear)</strong> — export options and PDF/CSV download.
          </li>
        </ul>

        <h3>Metric cards</h3>
        <ul>
          <li>
            <strong>Spend</strong> — USD cost attributed to your requests in the selected period.
          </li>
          <li>
            <strong>Tokens</strong> — input and output token totals.
          </li>
          <li>
            <strong>Requests</strong> — number of API/chat calls.
          </li>
          <li>
            <strong>Errors</strong> — failed requests (click through for context in exports).
          </li>
        </ul>
        <p>Click a card to expand a detailed chart for that metric.</p>

        <h3>Heatmap</h3>
        <p>
          Calendar-style heatmap for <strong>Spend</strong>, <strong>Tokens</strong>, or <strong>Requests</strong> —
          useful to see which days were busiest.
        </p>

        <h3>Top models &amp; insights</h3>
        <ul>
          <li>Ranked list of models by usage in the period.</li>
          <li>Short insight snippets (for example spend trend vs previous period) when data is available.</li>
          <li>Sample prompts section for recent activity (where enabled).</li>
        </ul>

        <h3>Export</h3>
        <ul>
          <li>
            <strong>CSV / Excel</strong> — tabular log suitable for spreadsheets.
          </li>
          <li>
            <strong>PDF</strong> — formatted snapshot of the current dashboard view.
          </li>
        </ul>

        <h3>Relation to budget</h3>
        <p>
          Activity spend reflects logged requests. Your profile <strong>Budget</strong> shows monthly{" "}
          <code>used / total $</code> for the current calendar month — the numbers should align closely with{" "}
          <em>This month</em> on this page.
        </p>
      </>
    ),
  },
  {
    id: "user-profile",
    title: "Profile & navigation",
    group: "Account",
    content: (
      <>
        <h2>Profile &amp; navigation</h2>
        <p>
          The profile control in the top bar shows your name or username. Open it to access:
        </p>
        <ul>
          <li>
            <strong>My Usage &amp; Activity</strong> — same page as the sidebar link.
          </li>
          <li>
            <strong>Budget</strong> — live <code>used / total $</code> for the current month.
          </li>
          <li>
            <strong>Theme</strong> — light or dark mode (synced to your account when signed in).
          </li>
          <li>
            <strong>Sign out</strong> — ends your session; sign in again with the method your organization uses (local,
            LDAP, or SSO).
          </li>
          <li>
            <strong>Administration</strong> — visible when your account has admin roles. Opens the first admin menu you
            are allowed to use (for example Groups or Dashboard for Super Admin). Scoped admins may not see every admin
            page; that is expected.
          </li>
        </ul>
        <p>
          On the chat page, profile and theme sit above the message area; other pages show the standard top bar with
          profile on the right.
        </p>
      </>
    ),
  },
  {
    id: "user-readonly",
    title: "Deactivated accounts",
    group: "Account",
    content: (
      <>
        <h2>Deactivated (read-only) accounts</h2>
        <p>
          If an administrator <strong>deactivates</strong> your account, you can still sign in but enter{" "}
          <strong>account-wide read-only</strong> mode:
        </p>
        <ul>
          <li>You can open <strong>Chat</strong>, <strong>Media</strong>, <strong>Recommendations</strong>, and <strong>My Usage &amp; Activity</strong>.</li>
          <li>You can read past chats and download media.</li>
          <li>You <strong>cannot</strong> send new messages, upload files, delete media, or change settings that write data.</li>
        </ul>
        <p>
          A banner explains read-only status. Contact your administrator if you believe deactivation was a mistake.
        </p>
        <Note>
          This is different from an administrator who holds <strong>API Key Admin</strong>. Those users remain fully able
          to chat and upload in <code>/app</code>; only the API Keys admin menu is added for them.
        </Note>
      </>
    ),
  },
  {
    id: "copyright",
    title: "Copyright",
    group: "Legal",
    content: (
      <>
        <h2>Copyright</h2>
        <p>
          Alpha Router was designed by <strong>Majid Arasskhani</strong> and developed by <strong>Cursor AI</strong> within
          the <strong>BitPin IT Department</strong>.
        </p>
        <p>
          <strong>About BitPin Exchange</strong> — Iranian digital asset platform focused on reliability, security, and
          transparent operations.
        </p>
        <div style={{ marginTop: "1rem" }}>
          <p style={{ margin: 0 }}>Copyright: BitPin IT Department</p>
          <p style={{ margin: "0.2rem 0 0" }}>Contact: IT@BitPin.co</p>
        </div>
      </>
    ),
  },
];
