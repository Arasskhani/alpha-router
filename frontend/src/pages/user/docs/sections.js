import { Fragment, jsx, jsxs } from "react/jsx-runtime";
import { PRODUCT_NAME_MARKED, TRADEMARK_OWNER } from "../../../lib/brand";
function Note({ children }) {
  return /* @__PURE__ */ jsx("div", { className: "docs-callout docs-callout-info", children });
}
function Warn({ children }) {
  return /* @__PURE__ */ jsx("div", { className: "docs-callout docs-callout-warn", children });
}
const userManualSections = [
  // ── Get started ───────────────────────────────────────────────────────────
  {
    id: "introduction",
    title: "Introduction",
    group: "Get started",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h1", { children: "User Manual" }),
      /* @__PURE__ */ jsxs("p", { className: "docs-lead", children: [
        "Welcome to Alpharouter \u2014 your organization\u2019s AI workspace. Use approved models in Chat, keep generated files in Media, collaborate in Projects, and track your own spend under Activity. Administrators configure models, budgets, and sign-in; this manual covers what you can do in the ",
        /* @__PURE__ */ jsx("strong", { children: "/app" }),
        " panel after you sign in."
      ] }),
      /* @__PURE__ */ jsxs("div", { className: "docs-cards", children: [
        /* @__PURE__ */ jsxs("div", { className: "docs-card", children: [
          /* @__PURE__ */ jsx("h3", { children: "Chat" }),
          /* @__PURE__ */ jsx("p", { children: "General chat, specialist Agents, citations, tools, private mode, export, and a prompt queue." })
        ] }),
        /* @__PURE__ */ jsxs("div", { className: "docs-card", children: [
          /* @__PURE__ */ jsx("h3", { children: "Projects" }),
          /* @__PURE__ */ jsx("p", { children: "Shared workspaces with members, rooms, chats, files, and project media." })
        ] }),
        /* @__PURE__ */ jsxs("div", { className: "docs-card", children: [
          /* @__PURE__ */ jsx("h3", { children: "Media" }),
          /* @__PURE__ */ jsx("p", { children: "Files you upload or generate, with search, filters, and optional cleanup." })
        ] }),
        /* @__PURE__ */ jsxs("div", { className: "docs-card", children: [
          /* @__PURE__ */ jsx("h3", { children: "Activity" }),
          /* @__PURE__ */ jsx("p", { children: "Your spend, tokens, models, heatmaps, trends, and CSV/PDF export." })
        ] })
      ] }),
      /* @__PURE__ */ jsxs("table", { className: "docs-table", children: [
        /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { children: [
          /* @__PURE__ */ jsx("th", { children: "Section" }),
          /* @__PURE__ */ jsx("th", { children: "Contents" })
        ] }) }),
        /* @__PURE__ */ jsxs("tbody", { children: [
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsxs("td", { children: [
              /* @__PURE__ */ jsx("a", { href: "#sign-in", children: "Sign-in" }),
              " & ",
              /* @__PURE__ */ jsx("a", { href: "#app-tour", children: "App tour" })
            ] }),
            /* @__PURE__ */ jsxs("td", { children: [
              "How you authenticate and navigate ",
              /* @__PURE__ */ jsx("code", { children: "/app" })
            ] })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("a", { href: "#user-chat", children: "Chat" }) }),
            /* @__PURE__ */ jsx("td", { children: "Sessions, models, streaming, attachments, tools, private mode" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("a", { href: "#user-projects", children: "Projects" }) }),
            /* @__PURE__ */ jsx("td", { children: "Shared workspaces, roles, rooms vs chats, files, media, invitations" })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsxs("td", { children: [
              /* @__PURE__ */ jsx("a", { href: "#user-media", children: "Media" }),
              " \xB7 ",
              /* @__PURE__ */ jsx("a", { href: "#user-activity", children: "Activity" }),
              " \xB7",
              " ",
              /* @__PURE__ */ jsx("a", { href: "#user-settings", children: "Settings" })
            ] }),
            /* @__PURE__ */ jsx("td", { children: "Personal library, activity, account preferences and security" })
          ] })
        ] })
      ] })
    ] })
  },
  {
    id: "sign-in",
    title: "Sign-in",
    group: "Get started",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Sign-in" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Open the Alpharouter URL your administrator gave you and sign in on ",
        /* @__PURE__ */ jsx("code", { children: "/login" }),
        ". Depending on your organization you may see:"
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Local account" }),
          " \u2014 username and password. If 2FA is enabled, enter the authenticator code (or a backup code) after the password."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Active Directory / LDAP" }),
          " \u2014 same username/password form; Alpharouter validates against your directory."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "SSO" }),
          " \u2014 SAML or OIDC buttons that redirect to your company identity provider, then return you to Alpharouter."
        ] })
      ] }),
      /* @__PURE__ */ jsx(Note, { children: "If sign-in fails, contact your administrator \u2014 they control which methods are enabled and whether your account is active." })
    ] })
  },
  {
    id: "app-tour",
    title: "Tour of /app",
    group: "Get started",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Tour of /app" }),
      /* @__PURE__ */ jsx("p", { children: "After sign-in you land in the user panel. Main navigation:" }),
      /* @__PURE__ */ jsxs("table", { className: "docs-table", children: [
        /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { children: [
          /* @__PURE__ */ jsx("th", { children: "Item" }),
          /* @__PURE__ */ jsx("th", { children: "Purpose" })
        ] }) }),
        /* @__PURE__ */ jsxs("tbody", { children: [
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "Chat" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              /* @__PURE__ */ jsx("code", { children: "/app/chat" }),
              " \u2014 conversations with AI models"
            ] })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "Projects" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              /* @__PURE__ */ jsx("code", { children: "/app/projects" }),
              " \u2014 shared workspaces you own or join"
            ] })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "Media" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              /* @__PURE__ */ jsx("code", { children: "/app/media" }),
              " \u2014 your uploads and generated files"
            ] })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "Activity" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              /* @__PURE__ */ jsx("code", { children: "/app/my-activity" }),
              " \u2014 personal spend and usage"
            ] })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "User Manual" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              /* @__PURE__ */ jsx("code", { children: "/app/manual" }),
              " \u2014 this guide"
            ] })
          ] })
        ] })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Top bar" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: PRODUCT_NAME_MARKED }),
          " brand / home context"
        ] }),
        /* @__PURE__ */ jsx("li", { children: "On Chat: model search / picker controls when available" }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Theme control (light / dark / system) and your ",
          /* @__PURE__ */ jsx("strong", { children: "profile menu" })
        ] })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Profile menu" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          "Monthly ",
          /* @__PURE__ */ jsx("strong", { children: "Budget" }),
          " (used vs limit) when a plan is assigned"
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Settings" }),
          " \u2014 general preferences, data control, security"
        ] }),
        /* @__PURE__ */ jsx("li", { children: /* @__PURE__ */ jsx("strong", { children: "Sign out" }) }),
        /* @__PURE__ */ jsxs("li", { children: [
          "If you also have admin roles: ",
          /* @__PURE__ */ jsx("strong", { children: "Administration" }),
          " opens ",
          /* @__PURE__ */ jsx("code", { children: "/admin" })
        ] })
      ] }),
      /* @__PURE__ */ jsx(Note, { children: "On Chat, the left app sidebar can appear as a peek rail \u2014 hover to expand navigation without leaving the conversation." })
    ] })
  },
  // ── Chat ──────────────────────────────────────────────────────────────────
  {
    id: "user-chat",
    title: "Chat overview",
    group: "Chat",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Chat overview" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/app/chat" }),
        ". Create multiple sessions, organize them into folders, choose general chat or an approved specialist Agent, and stream replies. Your chats sync to the server (except",
        " ",
        /* @__PURE__ */ jsx("a", { href: "#private-mode", children: "Private mode" }),
        ")."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: /* @__PURE__ */ jsx("a", { href: "#user-agents", children: "Specialist Agents & citations" }) }),
        /* @__PURE__ */ jsx("li", { children: /* @__PURE__ */ jsx("a", { href: "#chat-sessions", children: "Sessions & folders" }) }),
        /* @__PURE__ */ jsx("li", { children: /* @__PURE__ */ jsx("a", { href: "#chat-models", children: "Models" }) }),
        /* @__PURE__ */ jsx("li", { children: /* @__PURE__ */ jsx("a", { href: "#chat-streaming", children: "Sending, streaming & queue" }) }),
        /* @__PURE__ */ jsx("li", { children: /* @__PURE__ */ jsx("a", { href: "#chat-attachments", children: "Attachments & voice" }) }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("a", { href: "#chat-images", children: "Image generation" }),
          " \xB7 ",
          /* @__PURE__ */ jsx("a", { href: "#chat-videos", children: "Video generation" }),
          " \xB7 ",
          /* @__PURE__ */ jsx("a", { href: "#chat-speech", children: "Text to speech" })
        ] }),
        /* @__PURE__ */ jsx("li", { children: /* @__PURE__ */ jsx("a", { href: "#chat-tools", children: "Chat Tools" }) }),
        /* @__PURE__ */ jsx("li", { children: /* @__PURE__ */ jsx("a", { href: "#private-mode", children: "Private mode" }) }),
        /* @__PURE__ */ jsx("li", { children: /* @__PURE__ */ jsx("a", { href: "#chat-export", children: "Export & feedback" }) })
      ] })
    ] })
  },
  {
    id: "user-agents",
    title: "Specialist Agents & citations",
    group: "Chat",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Specialist Agents & citations" }),
      /* @__PURE__ */ jsx("p", { children: "The brain button in the chat box lists Agents your organization has published and that you are allowed to use. Visibility depends on both Agent and Knowledge access; a missing Agent may simply be restricted to another team. Create and publish Agents in Admin \u2192 Agent Studio." }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Chats start with no Agent. Switch one on when the domain matters; only one Agent runs at a time, switching it off returns the chat to the plain model, and the choice stays with that chat only. A tinted outline around the chat box marks Agent turns, and an Agent may still propose a handoff for your consent." }),
        /* @__PURE__ */ jsx("li", { children: "Organization-specific answers show citations. Open a citation to inspect its document, section/page, effective version, and Knowledge Base details that you are authorized to see." }),
        /* @__PURE__ */ jsx("li", { children: "If the specialist cannot attach the required citations, you may see a short safe message in English or Persian instead of an answer. That is expected: the platform refuses uncited claims rather than inventing sources. Try rephrasing, or ask an administrator if the Knowledge Base is incomplete." }),
        /* @__PURE__ */ jsx("li", { children: "Legal and Finance responses include a disclaimer. A citation supports the answer but does not replace professional approval." }),
        /* @__PURE__ */ jsx("li", { children: "If evidence is missing, expired, conflicting, or outside your permissions, a safe specialist should abstain or escalate instead of inventing policy." }),
        /* @__PURE__ */ jsx("li", { children: "A handoff transfers only bounded conversation context. Review the target Agent and approve the transfer when prompted." })
      ] }),
      /* @__PURE__ */ jsx(Warn, { children: "Treat citations as evidence, not instructions. Never share passwords, one-time codes, recovery secrets, or another person's confidential information with an Agent." }),
      /* @__PURE__ */ jsx(Note, { children: "Private mode does not persist the conversation and disables sensitive retrieval/memory according to policy. It does not grant extra access or bypass organization controls." })
    ] })
  },
  {
    id: "chat-sessions",
    title: "Sessions &amp; folders",
    group: "Chat",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Sessions & folders" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "New chat" }),
          " starts an empty session. Titles can update automatically from the conversation (unless you lock/rename them)."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Rename, delete, or move sessions into ",
          /* @__PURE__ */ jsx("strong", { children: "folders" }),
          " from the chat sidebar."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Sidebar groups recent activity: today, 1\u20133 days ago (scrollable), 3\u20137 days ago, and older than 7 days. Search finds sessions and, when available, message content on the server." }),
        /* @__PURE__ */ jsx("li", { children: "Switching sessions loads messages as needed. Long threads support scroll-to-bottom when you are not pinned to the latest reply." })
      ] }),
      /* @__PURE__ */ jsx(Note, { children: "Composer text and pending attachments are kept as a per-session draft while you switch chats in the same browser tab." })
    ] })
  },
  {
    id: "chat-models",
    title: "Models",
    group: "Chat",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Models" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Only models your administrator enabled appear in the picker. Some models may be ",
        /* @__PURE__ */ jsx("strong", { children: "Private" }),
        " \u2014 visible only to users and groups your admin assigned. Open the model picker from the chat chrome to choose a default model for the session. Some deployments allow selecting multiple models for a turn (compare replies); limits are enforced by the app."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Chat / reasoning models stream text replies." }),
        /* @__PURE__ */ jsx("li", { children: "Vision-capable models can accept image attachments in the prompt." }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Image models are used for generation (see ",
          /* @__PURE__ */ jsx("a", { href: "#chat-images", children: "Image generation" }),
          ")."
        ] })
      ] }),
      /* @__PURE__ */ jsx("p", { children: "You can save a preferred default model in Settings (or via the picker when that option is offered). Budget and model availability are organization policy \u2014 contact an admin if a model is missing." })
    ] })
  },
  {
    id: "chat-streaming",
    title: "Sending, streaming &amp; queue",
    group: "Chat",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Sending, streaming & queue" }),
      /* @__PURE__ */ jsxs("ol", { children: [
        /* @__PURE__ */ jsx("li", { children: "Type your prompt in the composer (Persian and English are both supported; direction follows the text)." }),
        /* @__PURE__ */ jsx("li", { children: "Send to start a turn. The assistant reply streams token by token." }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Use ",
          /* @__PURE__ */ jsx("strong", { children: "Stop" }),
          " to cancel generation for that session. Alpharouter still finalizes billing for work already done upstream when applicable."
        ] })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Prompt queue" }),
      /* @__PURE__ */ jsx("p", { children: "If a session is already generating, new prompts can be queued. They run one after another for that session so turns stay ordered. A compact queue bar stays in the composer so a long queue does not take over the chat. Open it to edit or remove items, or clear the whole queue." }),
      /* @__PURE__ */ jsx("h3", { children: "Read-only" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "If your account is deactivated, you can still open old chats but cannot send new messages. See",
        " ",
        /* @__PURE__ */ jsx("a", { href: "#user-readonly", children: "Deactivated accounts" }),
        "."
      ] }),
      /* @__PURE__ */ jsx(Warn, { children: "Sending requires remaining monthly budget. If you see a budget / payment error (HTTP 402), ask an administrator to assign or raise your plan." })
    ] })
  },
  {
    id: "chat-attachments",
    title: "Attachments &amp; voice",
    group: "Chat",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Attachments & voice" }),
      /* @__PURE__ */ jsx("h3", { children: "Files" }),
      /* @__PURE__ */ jsx("p", { children: "The paperclip opens an attach menu: upload a file, take a screenshot of a tab or window and crop it, or pick items from your Media library (project Media in a project chat). Files already in Media are attached by reference \u2014 they are not stored a second time." }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Images" }),
          " (for example ",
          /* @__PURE__ */ jsx("code", { children: "jpg" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: "png" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: "webp" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: "gif" }),
          ") can be sent to vision-capable models."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Video" }),
          " (for example ",
          /* @__PURE__ */ jsx("code", { children: "mp4" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: "mov" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: "mkv" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: "webm" }),
          ") and ",
          /* @__PURE__ */ jsx("strong", { children: "audio" }),
          " (for example ",
          /* @__PURE__ */ jsx("code", { children: "mp3" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: "ogg" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: "wav" }),
          ",",
          " ",
          /* @__PURE__ */ jsx("code", { children: "m4a" }),
          ") can be attached and play in the thread; the model receives a short note that the file was attached (not raw multimedia understanding unless your deployment adds that)."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Documents" }),
          " (PDF, Office, text, CSV, and similar) are processed for extractable text where supported."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Executables, archives, HTML/SVG, and other blocked types stay unavailable. Oversized files and the per-message file count show an error before send (limits come from your administrator's Storage settings)." }),
        /* @__PURE__ */ jsx("li", { children: "In Private Mode, Media attach works for images, audio/video, and plain-text files, processed locally. Some Office/PDF types still need Private Mode off so the server can extract text." })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Voice" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Record or upload audio for transcription into the composer." }),
        /* @__PURE__ */ jsx("li", { children: "Choose voice recording language in Settings \u2192 General (English or Persian) so transcription matches your speech." }),
        /* @__PURE__ */ jsx("li", { children: "Optional refine step can clean up a transcript before you send it as a prompt." })
      ] })
    ] })
  },
  {
    id: "chat-images",
    title: "Image generation",
    group: "Chat",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Image generation" }),
      /* @__PURE__ */ jsx("p", { children: "When an image-capable model (or image tool flow) is selected, Alpharouter generates images through the platform image API. Generation can continue in the background for that session; you can navigate away and return while a job is pending." }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Prompt enhancement / translation helpers may be available from the composer for image prompts." }),
        /* @__PURE__ */ jsx("li", { children: "Completed images appear in the thread and usually in your Media library (unless Private mode)." }),
        /* @__PURE__ */ jsx("li", { children: "Costs count against your monthly budget like other paid requests." }),
        /* @__PURE__ */ jsx("li", { children: "Some image models (for example OpenAI GPT Image) can take well over a minute. If the UI reports a gateway timeout, retry once and check Media \u2014 the image may still have finished on the server after the browser connection dropped." })
      ] })
    ] })
  },
  {
    id: "chat-videos",
    title: "Video generation",
    group: "Chat",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Video generation" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Enable ",
        /* @__PURE__ */ jsx("strong", { children: "Video Generation" }),
        " in Chat Tools to create clips from a text prompt (text-to-video) or from an attached / prior image as the first frame (image-to-video). Jobs run asynchronously; a pending placeholder stays in the thread until the clip is ready."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Choose duration, resolution, and aspect ratio from the tools menu before sending." }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Optionally enable ",
          /* @__PURE__ */ jsx("strong", { children: "Generate audio" }),
          " when the selected video model supports soundtrack output."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Completed videos appear in the thread and in your Media library (unless Private mode)." }),
        /* @__PURE__ */ jsx("li", { children: "Only one video job runs at a time per user by default; costs count against your monthly budget." })
      ] })
    ] })
  },
  {
    id: "chat-speech",
    title: "Text to speech",
    group: "Chat",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Text to speech" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Enable ",
        /* @__PURE__ */ jsx("strong", { children: "Text to Speech" }),
        " in Chat Tools to turn your message text into spoken audio. Image and video generation tools are turned off while speech generation is on (and the reverse)."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Pick a voice and playback speed from the tools menu before sending." }),
        /* @__PURE__ */ jsx("li", { children: "The platform generates audio from your message text (subject to a maximum character length shown in the tools menu)." }),
        /* @__PURE__ */ jsx("li", { children: "Completed audio appears in the thread and in your Media library (unless Private mode)." }),
        /* @__PURE__ */ jsx("li", { children: "Costs count against your monthly budget like other paid requests." })
      ] }),
      /* @__PURE__ */ jsxs(Note, { children: [
        "Voice ",
        /* @__PURE__ */ jsx("em", { children: "recording" }),
        " (microphone \u2192 transcript into the composer) is separate from Text to Speech. See",
        " ",
        /* @__PURE__ */ jsx("a", { href: "#chat-attachments", children: "Attachments & voice" }),
        "."
      ] })
    ] })
  },
  {
    id: "chat-tools",
    title: "Chat Tools",
    group: "Chat",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Chat Tools" }),
      /* @__PURE__ */ jsx("p", { children: "Open the tools menu on the composer to enable capabilities for the current session. Availability depends on your deployment and model." }),
      /* @__PURE__ */ jsxs("table", { className: "docs-table", children: [
        /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { children: [
          /* @__PURE__ */ jsx("th", { children: "Tool" }),
          /* @__PURE__ */ jsx("th", { children: "What it does" })
        ] }) }),
        /* @__PURE__ */ jsxs("tbody", { children: [
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "Web search" }) }),
            /* @__PURE__ */ jsx("td", { children: "Lets the model request web search results (depth settings may apply)." })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "Web fetch" }) }),
            /* @__PURE__ */ jsx("td", { children: "Fetches the content of a URL the model chooses (subject to server SSRF protections)." })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "Image generation" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              "Enables text-to-image and image-to-image flows from chat. See",
              " ",
              /* @__PURE__ */ jsx("a", { href: "#chat-images", children: "Image generation" }),
              "."
            ] })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "Video generation" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              "Creates clips from text or an attached image. See ",
              /* @__PURE__ */ jsx("a", { href: "#chat-videos", children: "Video generation" }),
              "."
            ] })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "Text to speech" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              "Generates spoken audio from your message text. See ",
              /* @__PURE__ */ jsx("a", { href: "#chat-speech", children: "Text to speech" }),
              "."
            ] })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: /* @__PURE__ */ jsx("strong", { children: "Code interpreter" }) }),
            /* @__PURE__ */ jsxs("td", { children: [
              "Runs Python in an isolated sandbox for calculation / data tasks. The model must emit a fenced",
              " ",
              /* @__PURE__ */ jsx("code", { children: "python" }),
              " code block for anything to execute. Spreadsheet attachments reach the sandbox as CSV (use Code interpreter outside Private mode for Excel). Valid PDF, CSV, JSON, text, and Markdown outputs are saved to your Media library and shown as authenticated download links in Chat, including files named in Persian or any other language. Generated files are not persisted in Private mode. Extra budget hold may apply while the tool is on. While the tool is on, the model list hides models that were measured as unable to complete this flow; if your current model is one of them, Chat switches to a suitable model and tells you why. If all execution slots are occupied, Chat reports that Code Interpreter is busy before sending the request to the model; wait for the indicated retry interval and try again. Pressing Stop also cancels the active sandbox job."
            ] })
          ] })
        ] })
      ] }),
      /* @__PURE__ */ jsx(Note, { children: "Tool preferences are remembered per session when you change them. Turn off tools you do not need to avoid unexpected calls or cost." })
    ] })
  },
  {
    id: "private-mode",
    title: "Private mode",
    group: "Chat",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Private mode" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Private mode keeps a chat on your device: sessions and messages stay in local browser storage; media uses IndexedDB. Alpharouter does ",
        /* @__PURE__ */ jsx("strong", { children: "not" }),
        " persist that session\u2019s messages to the server."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          "Enabling Private mode requires confirmation and is ",
          /* @__PURE__ */ jsx("strong", { children: "not reversible" }),
          " for that chat."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Model calls still go through Alpharouter (and count toward budget) \u2014 only chat history storage is local." }),
        /* @__PURE__ */ jsx("li", { children: "On logout, private chats are cleared unless your browser has persistence explicitly enabled by policy/local flag (administrators document this for your site)." }),
        /* @__PURE__ */ jsx("li", { children: "Private chats are excluded from Settings \u2192 Data Control server export." })
      ] }),
      /* @__PURE__ */ jsx(Warn, { children: "Private mode is not a substitute for a secure endpoint. Anyone with access to your browser profile may read local private data. Use organization SSO and device policies as instructed by your admin." })
    ] })
  },
  {
    id: "chat-memory",
    title: "Memory",
    group: "Chat",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Memory" }),
      /* @__PURE__ */ jsx("p", { children: "Personalization and Memory are two additive context layers for non-private chats (they never replace session messages):" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Account profile" }),
          " \u2014 directory fields from your user record (Company, Department, Job title, Report to). Read-only in Settings \u2192 Personalization; managed by admins or directory sync."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Automatic memory" }),
          " \u2014 durable facts learned from your non-private chats (preferences, constraints, health notes you discussed, recurring work context). Learning is silent. Manage it in Settings \u2192 Memory."
        ] })
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Use my memories in chat" }),
          " (on by default) \u2014 inject relevant memories into new non-private turns."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Automatically learn new things about me" }),
          " (on by default) \u2014 extract new facts after a conversation. Turn this off to stop learning while still using existing memories."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Private mode chats do not receive profile context or memories, and are never mined." }),
        /* @__PURE__ */ jsx("li", { children: "You can disable, delete, or export memories. Deleting a fact also prevents it from being learned again from old chats. Delete-all does the same for every fact." })
      ] }),
      /* @__PURE__ */ jsx(Note, { children: "Memories outlive individual chats. Prefer this for durable facts you are comfortable keeping on the server for your account." })
    ] })
  },
  {
    id: "chat-export",
    title: "Export &amp; feedback",
    group: "Chat",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Export & feedback" }),
      /* @__PURE__ */ jsx("h3", { children: "Export" }),
      /* @__PURE__ */ jsx("p", { children: "From a conversation you can export content as PDF or DOCX (server-rendered for faithful Persian/RTL layout when needed). CSV helpers may be available for tabular markdown in replies." }),
      /* @__PURE__ */ jsx("h3", { children: "Feedback" }),
      /* @__PURE__ */ jsx("p", { children: "Rate assistant outputs (thumbs / reasons when prompted). Feedback helps administrators understand model quality; it does not change your budget." }),
      /* @__PURE__ */ jsx("h3", { children: "Regenerate" }),
      /* @__PURE__ */ jsx("p", { children: "Where offered, regenerate requests a new assistant reply for the same user turn (additional usage applies)." })
    ] })
  },
  // ── Projects ──────────────────────────────────────────────────────────────
  {
    id: "user-projects",
    title: "Projects",
    group: "Projects",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Projects" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/app/projects" }),
        ". A project is a shared workspace: members, rooms, chats, files, and media belong to the project \u2014 not to one person's private Chat or Media library."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "My projects and Explore" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "My projects" }),
          " lists workspaces you belong to. Archived and pending-deletion projects appear in their own sections so they stay out of the active list."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Explore" }),
          " lists ",
          /* @__PURE__ */ jsx("em", { children: "public" }),
          " projects visible to every signed-in user. Private projects never appear here."
        ] })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Workspace tabs" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Opening a project lands on ",
        /* @__PURE__ */ jsx("strong", { children: "Chats" }),
        ". Tabs from left to right:"
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Chats" }),
          " \u2014 shared AI threads for this project."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Rooms" }),
          " \u2014 member-only human discussion (hidden from public visitors who are not members)."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Resources" }),
          " \u2014 documents submitted for Knowledge review."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Media" }),
          " \u2014 the project file library."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Overview" }),
          " \u2014 member, chat, and file counts. Spend for the last 30 days is visible only to Owners, the Primary Owner, and reports admins."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Activity" }),
          " \u2014 full spend and usage charts (Owners and Primary Owner only)."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Members" }),
          " then ",
          /* @__PURE__ */ jsx("strong", { children: "Settings" }),
          " \u2014 people, then project configuration."
        ] })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Roles" }),
      /* @__PURE__ */ jsxs("table", { className: "docs-table", children: [
        /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { children: [
          /* @__PURE__ */ jsx("th", { children: "Role" }),
          /* @__PURE__ */ jsx("th", { children: "What you can do" })
        ] }) }),
        /* @__PURE__ */ jsxs("tbody", { children: [
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Primary Owner" }),
            /* @__PURE__ */ jsx("td", { children: "The person who created the project. Same management as Owner, plus changing Owner access and archive, restore, delete, and purge. There is exactly one Primary Owner; they cannot leave or be demoted." })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Owner" }),
            /* @__PURE__ */ jsx("td", { children: "Manage members (Contributor and Viewer), settings, Activity, and project files. Cannot archive or delete the project, and cannot change another Owner's access. Extra Owners may leave." })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Contributor" }),
            /* @__PURE__ */ jsx("td", { children: "Rooms, Chat, upload resources and media, and edit project settings that Contributors are allowed to change. Cannot open Activity." })
          ] }),
          /* @__PURE__ */ jsxs("tr", { children: [
            /* @__PURE__ */ jsx("td", { children: "Viewer" }),
            /* @__PURE__ */ jsx("td", { children: "Read rooms, chats, resources, and media. Viewers cannot send messages or change membership." })
          ] })
        ] })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Rooms" }),
      /* @__PURE__ */ jsxs("p", { children: [
        /* @__PURE__ */ jsx("strong", { children: "Rooms" }),
        " are member-only human threads. There is no model, no tools, no Agent, and no AI spend. While you are on the Rooms tab, the AI chat sidebar is hidden so only the room list is on the left. Public visitors who are not project members do not see the Rooms tab. Room text is not copied into project memory and is not sent to the model."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Owners and Contributors can create rooms, write, reply, and (for their own messages) edit or delete. Reply and the message actions use the same control style as Chat." }),
        /* @__PURE__ */ jsx("li", { children: "Hover a room in the list to show the \xD7 control, then confirm \u2014 the same pattern as deleting a chat." }),
        /* @__PURE__ */ jsx("li", { children: "Viewers can read rooms but cannot write, reply, or hand off to Chat." })
      ] }),
      /* @__PURE__ */ jsxs("p", { children: [
        "When a room reaches a decision, Owners and Contributors can use ",
        /* @__PURE__ */ jsx("strong", { children: "Send decision to Chat" }),
        ". Only the edited brief is placed in the new chat box so you can review it and press Send \u2014 it is not sent to the model automatically, and the full room transcript is not copied. The workspace then opens that new chat."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Shared chat" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Project chats live under the workspace ",
        /* @__PURE__ */ jsx("strong", { children: "Chats" }),
        " tab. They are shared with members of that project. They are not copies of your personal ",
        /* @__PURE__ */ jsx("code", { children: "/app/chat" }),
        " sessions, and Private Mode is not available in a project chat. Tools, model, and Agent in the composer are yours alone \u2014 other members of the same thread keep their own composer settings. Owners and Contributors can pin a thread for everyone in the project, and can copy a link with ",
        /* @__PURE__ */ jsx("code", { children: "?session=" }),
        " to open that chat directly \u2014 even if it is older than the first page of the sidebar. Re-entering a project restores the last thread you had open. Pins and new messages appear for every member without a refresh. Each user prompt shows the sender's name. Making a project",
        " ",
        /* @__PURE__ */ jsx("strong", { children: "Public" }),
        " requires typing ",
        /* @__PURE__ */ jsx("code", { children: "PUBLIC" }),
        "."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Activity" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "The Primary Owner and Owners can open the ",
        /* @__PURE__ */ jsx("strong", { children: "Activity" }),
        " tab in the workspace (or",
        " ",
        /* @__PURE__ */ jsx("code", { children: "/app/projects/<id>/activity" }),
        ") to see spend, tokens, and charts for that project only. Contributors and Viewers do not have this tab."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Resources vs Media" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Resources" }),
          " are documents submitted through the Knowledge pipeline (malware scan, text extraction, review). Owners and Contributors can upload up to 20 files at a time. Allowed types:",
          " ",
          /* @__PURE__ */ jsx("code", { children: ".pdf" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: ".docx" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: ".pptx" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: ".xlsx" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: ".txt" }),
          ",",
          " ",
          /* @__PURE__ */ jsx("code", { children: ".md" }),
          " / ",
          /* @__PURE__ */ jsx("code", { children: ".markdown" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: ".html" }),
          " / ",
          /* @__PURE__ */ jsx("code", { children: ".htm" }),
          ", ",
          /* @__PURE__ */ jsx("code", { children: ".csv" }),
          ",",
          " ",
          /* @__PURE__ */ jsx("code", { children: ".json" }),
          ". Until a file is ",
          /* @__PURE__ */ jsx("strong", { children: "Published" }),
          ", members see",
          " ",
          /* @__PURE__ */ jsx("strong", { children: "Waiting for Admin Approval" }),
          ". After an admin publishes the version, project chat may inject short excerpts from that file when Settings allows it (Owners: ",
          /* @__PURE__ */ jsx("strong", { children: "Use project resources" }),
          "). That is not the same as Agent Knowledge retrieval: publishing a Knowledge ",
          /* @__PURE__ */ jsx("em", { children: "release" }),
          " and building the vector index is for Agents bound to that Knowledge Base, not for ordinary project chat."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Media" }),
          " are binary files (images, video, audio, uploads) stored in the project library. Images, video, audio, and other files generated or attached in a project chat are stored here (not in your personal Media library) so every member can open them. If the project is over quota, the file is kept only for the sender."
        ] })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Memory and grounding" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Owners can add short project memory facts in Settings and optionally allow granted memory from other projects. Room messages never become memory. Resource excerpts and memory are injected only into AI chats of this project \u2014 never into Rooms, and never into your personal ",
        /* @__PURE__ */ jsx("code", { children: "/app/chat" }),
        " sessions."
      ] }),
      /* @__PURE__ */ jsx("h4", { children: "Automatic project memory" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "With ",
        /* @__PURE__ */ jsx("strong", { children: "Automatically learn from project chats" }),
        " enabled in Settings, the assistant quietly keeps durable team facts it picks up from the project's AI chats \u2014 decisions, conventions, the stack, deadlines, responsibilities, client constraints \u2014 and reuses them in later turns so you do not have to repeat them."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          "Learned facts belong to the ",
          /* @__PURE__ */ jsx("strong", { children: "project" }),
          ", not to you: every member sees them, and each fact records who contributed it and which chat it came from."
        ] }),
        /* @__PURE__ */ jsx("li", { children: "Only the AI chat tab is mined. Rooms, private chats, and your personal chats outside the project are never read." }),
        /* @__PURE__ */ jsx("li", { children: "Personal and sensitive details \u2014 health, finances, and private facts about individuals \u2014 are dropped and never stored as project memory, even if they were mentioned in the chat." }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Your ",
          /* @__PURE__ */ jsx("strong", { children: "personal" }),
          " memory is never used inside a project chat, and a project chat never adds anything to it. The two are fully separated."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "In Settings, Owners can filter Manual vs Learned facts, disable or delete a single fact, or use",
          " ",
          /* @__PURE__ */ jsx("strong", { children: "Delete all learned facts" }),
          " to clear everything the assistant learned while keeping hand-written facts. A deleted fact is not learned again from the same chats."
        ] })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Invitations" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "The Primary Owner and Owners create a link (Contributor or Viewer only \u2014 never Owner or Primary Owner). Share the link, or optionally email it to an existing Alpharouter user when SMTP is configured. If email is unavailable, the invitation is still created: copy the link from the dialog. Claim invitations at",
        " ",
        /* @__PURE__ */ jsx("code", { children: "/app/projects/invite" }),
        "."
      ] }),
      /* @__PURE__ */ jsx(Note, { children: "Personal Chat and personal Media stay private to you. Project content is visible to project members according to their role." })
    ] })
  },
  // ── Media ─────────────────────────────────────────────────────────────────
  {
    id: "user-media",
    title: "Media",
    group: "Media",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Media" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/app/media" }),
        ". Browse files associated with your account \u2014 uploads and generations from chat (images, video, audio, and documents; non-private)."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Search and filter by kind or date as offered in the library UI." }),
        /* @__PURE__ */ jsx("li", { children: "Open, download, or delete individual items; bulk delete and ZIP download when available." }),
        /* @__PURE__ */ jsx("li", { children: "Quota meter shows how much of your storage allowance you use (limit set by administrators)." }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Optional ",
          /* @__PURE__ */ jsx("strong", { children: "cleanup schedule" }),
          ": enable automatic deletion of media older than N days at a time you choose."
        ] })
      ] }),
      /* @__PURE__ */ jsx(Note, { children: "Global retention policies set by administrators may delete media earlier than your personal schedule. When in doubt, download copies you need to keep." })
    ] })
  },
  // ── Usage ─────────────────────────────────────────────────────────────────
  {
    id: "user-activity",
    title: "Activity",
    group: "Activity",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Activity" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Path: ",
        /* @__PURE__ */ jsx("code", { children: "/app/my-activity" }),
        ". Personal analytics for your account only (not the whole organization). The same tabbed Activity experience administrators use is scoped to ",
        /* @__PURE__ */ jsx("strong", { children: "you" }),
        ": there is no user filter and no organization-wide \u201Ctop users\u201D view."
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Tabs" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Overview" }),
          " \u2014 KPIs, usage and token charts, request heatmap, and breakdowns by model and app."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Trends" }),
          " \u2014 how your models and apps change over the selected period."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Explore" }),
          " \u2014 pick metric, grouping, rollup, and chart type; export a PDF snapshot."
        ] })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Toolbar" }),
      /* @__PURE__ */ jsx("ul", { children: /* @__PURE__ */ jsx("li", { children: "Period, timezone, filters (model, app, status), group-by, CSV/PDF export." }) }),
      /* @__PURE__ */ jsx("p", { children: "Your monthly budget remaining is also visible from the profile menu. Organization-wide dashboards and gateway API key analytics are administrator-only." }),
      /* @__PURE__ */ jsxs(Note, { children: [
        "If your administrator assigns you a ",
        /* @__PURE__ */ jsx("strong", { children: "gateway API key" }),
        " for an external tool (scripts, IDEs, Kilo Code), that key's spend is tracked against the key's credit pool \u2014 not your personal monthly budget. Your Activity page still shows requests attributed to your user when the key owner is you. Traffic from your ",
        /* @__PURE__ */ jsx("strong", { children: "personal API key" }),
        " (Settings \u2192 API Key) appears in Activity and admin logs with your key name."
      ] })
    ] })
  },
  // ── Account ───────────────────────────────────────────────────────────────
  {
    id: "user-settings",
    title: "Settings",
    group: "Account",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Settings" }),
      /* @__PURE__ */ jsx("p", { children: "Open Settings from the profile menu:" }),
      /* @__PURE__ */ jsx("h3", { children: "General" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Time zone for activity displays" }),
        /* @__PURE__ */ jsx("li", { children: "Voice recording language (English / Persian)" }),
        /* @__PURE__ */ jsx("li", { children: "Chat notification \u2014 optional toast (and sound) when a chat finishes while you are in another chat or the tab is in the background" }),
        /* @__PURE__ */ jsx("li", { children: "Theme: light, dark, or system" })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Personalization" }),
      /* @__PURE__ */ jsx("ul", { children: /* @__PURE__ */ jsx("li", { children: "View read-only account profile fields (Company, Department, Job title, Report to) used in non-private chats" }) }),
      /* @__PURE__ */ jsx("h3", { children: "Memory" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Toggle whether memories are referenced in non-private chats (default on)" }),
        /* @__PURE__ */ jsx("li", { children: "Toggle whether new facts are learned automatically (default on)" }),
        /* @__PURE__ */ jsx("li", { children: "Review, disable, delete, or export learned memories; delete-all asks for three confirmations" })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "Data Control" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Export" }),
          " server-side chats as JSON"
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Import" }),
          " JSON from Alpharouter, ChatGPT, or Open WebUI formats (merges into your account)"
        ] })
      ] }),
      /* @__PURE__ */ jsx("p", { children: "Private-mode chats are not included in server export." }),
      /* @__PURE__ */ jsx("h3", { children: "Security" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsx("li", { children: "Local accounts: change password; set up or disable TOTP 2FA and store backup codes safely" }),
        /* @__PURE__ */ jsx("li", { children: "LDAP / SAML / OIDC accounts: password and 2FA are managed at your identity provider" })
      ] }),
      /* @__PURE__ */ jsx("h3", { children: "API Key" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "Create one ",
        /* @__PURE__ */ jsx("strong", { children: "personal API key" }),
        " for OpenAI-compatible tools (scripts, IDEs, Kilo Code). Usage debits your monthly budget (same pool as Chat). Revoke permanently from Settings when rotating credentials; create a new key only after revoking the old one."
      ] }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          "Base URL: your Alpharouter ",
          /* @__PURE__ */ jsx("code", { children: "/v1" }),
          " endpoint (shown after creation)."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          "Header: ",
          /* @__PURE__ */ jsx("code", { children: "Authorization: Bearer <your-key>" })
        ] }),
        /* @__PURE__ */ jsx("li", { children: "The plaintext key is shown once at creation \u2014 store it securely." })
      ] })
    ] })
  },
  {
    id: "user-profile",
    title: "Budget, theme &amp; logout",
    group: "Account",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Budget, theme & logout" }),
      /* @__PURE__ */ jsxs("ul", { children: [
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Budget" }),
          " \u2014 monthly USD allowance from your plan. Chat, images, tools, and your",
          " ",
          /* @__PURE__ */ jsx("strong", { children: "personal API key" }),
          " (Settings \u2192 API Key) consume it. Separate ",
          /* @__PURE__ */ jsx("strong", { children: "gateway API keys" }),
          " issued by administrators use their own credit pool."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Theme" }),
          " \u2014 follows Settings; applied across the app."
        ] }),
        /* @__PURE__ */ jsxs("li", { children: [
          /* @__PURE__ */ jsx("strong", { children: "Sign out" }),
          " \u2014 ends your session and revokes prior tokens for your account. Private local data is cleared unless persistence is enabled for your browser."
        ] })
      ] })
    ] })
  },
  {
    id: "user-readonly",
    title: "Deactivated accounts",
    group: "Account",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Deactivated accounts" }),
      /* @__PURE__ */ jsxs("p", { children: [
        "If an administrator deactivates your account, you can still sign in to ",
        /* @__PURE__ */ jsx("strong", { children: "read" }),
        " your existing chat history and media, but you cannot send new messages, generate images, or create new spend. Contact your administrator to restore access."
      ] }),
      /* @__PURE__ */ jsx(Note, { children: "This is different from holding an admin role such as API Key Admin. Those roles add admin menus; they do not deactivate chat." })
    ] })
  },
  // ── Legal ─────────────────────────────────────────────────────────────────
  {
    id: "copyright",
    title: "Copyright",
    group: "Legal",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Copyright" }),
      /* @__PURE__ */ jsx("p", { children: "Copyright \xA9 2026 Majid Arasskhani." }),
      /* @__PURE__ */ jsxs("p", { children: [
        "The ",
        PRODUCT_NAME_MARKED,
        " source code is licensed under the MIT License. Use, modification, and redistribution are permitted under that license. The name and logos are not included; see",
        " ",
        /* @__PURE__ */ jsx("a", { href: "#trademarks", children: "Trademarks" }),
        "."
      ] }),
      /* @__PURE__ */ jsx("p", { children: "Contact: Majid.Arasskhani@gmail.com" })
    ] })
  },
  {
    id: "trademarks",
    title: "Trademarks",
    group: "Legal",
    content: /* @__PURE__ */ jsxs(Fragment, { children: [
      /* @__PURE__ */ jsx("h2", { children: "Trademarks" }),
      /* @__PURE__ */ jsxs("p", { children: [
        PRODUCT_NAME_MARKED,
        ", Alpha Router, AlphaRouter, and the product logos are trademarks of",
        " ",
        TRADEMARK_OWNER,
        "."
      ] }),
      /* @__PURE__ */ jsx("p", { children: "The MIT License covers the source code only. It does not grant permission to use these marks for a fork, a competing product, or any use that implies an official relationship." })
    ] })
  }
];
export {
  userManualSections
};
