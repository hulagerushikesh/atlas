# E7 — Atlas inside the assistants people already use (MCP)

Written 2026-11-28, when the owner chose this as the step after Drive (D11).
Reference setup: the owner's company runs Microsoft 365 Copilot with
SharePoint, Jira, Confluence, Teams and a few MCP servers. People there do not
want another chat window; they want their assistant to know the company's
documents, with the company's permissions.

## 1. What is built (T34)

- **`POST /mcp`** — an MCP server over Streamable HTTP, stateless, JSON
  responses, protocol 2025-11-25 (the Python SDK `mcp` 2.3 also speaks the
  2026-07-28 revision). Three read-only tools:
  - `list_sheets` — the sheets the caller may read;
  - `list_sources(sheet)` — the documents on a sheet the caller may read;
  - `search(question, sheet, limit=8)` — the best passages, each with a
    `[n]` marker, its source and page. The assistant writes the answer with
    its own model, so Atlas spends one embedding per search (≈₹0.0001),
    never a generation, and the daily spend cap still applies.
- **Personal keys** (`/me/keys`, console: your email → *AI assistants*). A
  key acts as the person who made it: same sheets, same groups, same Drive
  sharing (`email:` and `domain:` tokens). It is re-checked on every call:
  revoking it or removing the person stops it on the next call. A key cannot
  make another key. 30 calls a minute, ten keys per person.
- The key may come as `Authorization: Bearer …` or `X-API-Key: …` (Copilot
  Studio's "API key" option names a header and sends the bare key).
- A browser session cookie is refused at `/mcp`: an assistant holds a key
  its owner made for it and can lose on its own. That is also why the SDK's
  Host/Origin checks are off: they protect servers that trust whoever can
  reach them, and this one trusts only a key a web page cannot hold.
- The tools' descriptions tell the assistant to treat passage text as
  content, not instructions. That lowers, and does not remove, the risk of a
  document steering the assistant; the assistant's own guards still apply.

## 2. Which assistants can use it now

| Assistant | How it connects | Works with a personal key? |
|---|---|---|
| Claude Code, Cursor, VS Code, most desktop clients | URL + header | Yes |
| Microsoft Copilot Studio (agents in M365 Copilot and Teams) | Streamable HTTP; API key (header) or OAuth 2.0 with dynamic client registration ([Microsoft][ms]) | Yes, API key: each user of the agent supplies their own key |
| Claude.ai custom connectors, ChatGPT | OAuth 2.1 with dynamic client registration; Claude's callback is `https://claude.ai/api/mcp/auth_callback` ([Anthropic][claude]) | Not yet: needs E7.4 |

## 3. What is not done

- **E7.4 OAuth.** Claude.ai and ChatGPT connectors, and Copilot Studio's
  smoother OAuth path, need Atlas to act as an OAuth authorisation server
  (protected-resource metadata, dynamic client registration, Google sign-in
  behind it) per the MCP authorisation spec ([spec][auth]). About a day of
  work; worth it once a real user asks for one of those clients.
- No `ask` tool (Atlas's own cited answer): it would spend a generation per
  call and duplicate what the assistant already does. Add it if a client
  without its own model needs it.
- Keys do not expire on their own; people revoke them in the console.

[ms]: https://learn.microsoft.com/microsoft-copilot-studio/mcp-add-existing-server-to-agent
[claude]: https://claude.com/docs/connectors/building/authentication
[auth]: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
