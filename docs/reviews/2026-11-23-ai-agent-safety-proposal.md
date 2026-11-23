# Proposal: using thickanon safely with AI coding agents

Date: 23.11.2026
Scope: thickanon v0.1.0 (`C:\PROGRAMMING\thickAnonymizer`, commit `4719ba6`) together with Claude Code 2.1.330 on Windows 11. GitHub Copilot agent and Codex CLI are covered briefly in section 7.
Status: proposal only. No repository file was changed.

---

## 1. Summary

**Goal.** Real PII must never reach the model provider. The user still wants a useful loop: the agent reads and edits anonymized documents or code and the user de-anonymizes the result afterwards.

**Main finding.** A coding agent is not a chat window. It has a shell and the file system of the user. Anonymizing a folder protects nothing if the agent can also reach the backup folder, the mapping file, the original files, the passphrase or the `thickanon deanonymize` command. On native Windows the Claude Code sandbox does not run at all, so no Claude Code setting can stop a Python or PowerShell script from reading those files. Permission rules and hooks are useful, but on native Windows they are guard rails and not a boundary.

**Recommendation.**

1. **Keep the secrets out of the agent's world.** Run the agent on a separate anonymized working copy. Keep originals, backup, mapping and passphrase in a vault that the agent process cannot reach. On Windows, the practical boundary is a WSL2 distribution or a dev container that mounts only the working copy (Design E).
2. **Make thickanon produce that working copy safely.** Add an export and import mode to the CLI (Design B): copy to an output folder, encrypted mapping only, passphrase never on the command line, a wider residual scan that fails the export, no `.git` history, no unsupported files.
3. **Add a hook tripwire** that runs the thickanon detector on prompts and tool results and stops the turn when PII shows up (Design C). It catches detector misses and mistakes. It cannot be the only control because some context never passes a hook.
4. **Treat the rewriting proxy (Design D) as a later experiment.** It covers every byte that leaves the machine, but Anthropic's own gateway guide says a gateway should "inspect without modifying". It is the most work and the most fragile.

**Top 3 designs** (by value for effort): E (isolated container or WSL2 with only the anonymized copy), B (thickanon agent export/import plus a no-deanonymize MCP server), C (detector hooks as tripwire).

**Key limits that no design removes.**

- Detection recall. Every design depends on what the detector finds. Today the residual scan only checks IPv4 and email. The CLI default mode never anonymizes hostnames (see 2.2). Office headers, footers, comments, notes and document properties are not processed at all.
- Re-identification from context (job titles, project names, dates) is not covered by token replacement.
- On native Windows, Claude Code has no OS-level sandbox. Read deny rules do not cover a script that opens files itself.

---

## 2. What thickanon does today (facts that matter for agents)

All references are to `src/thickanon/`.

### 2.1 Behaviour

| Area | Current behaviour | Source |
| - | - | - |
| Write mode | Edits files in place. An output folder exists in the core (`apply_scan(..., output_root=...)`) and in the desktop app, but the CLI has no `--output` option. | `core/plan.py` `apply_scan`, `cli.py`, `ui/api.py` line 486 |
| De-anonymize | Always in place. No output folder. | `core/orchestrator.py` `deanonymize_paths` |
| Mapping | JSON `{type, value, token}` pairs. Plaintext by default. AES-GCM with PBKDF2 (200.000 iterations) when a passphrase is given. Continued across runs by `load_or_new`, so tokens stay stable. | `core/mapping.py` |
| Passphrase on CLI | Only `--passphrase <value>` on the command line. No prompt, no file, no environment variable. | `cli.py` |
| Location guards | Mapping, backup and output must be outside `--root`. The app places them *beside* the root (`<root>.thickanon-mapping.json`, `<root.name>.thickanon-backup`). | `core/orchestrator.py`, UI spec section D |
| Tokens | `[TYPE_N]`, matched on the way back by `\[[A-Z_]+_\d+\]`. Unknown tokens stay verbatim and are counted. | `core/anonymize.py` |
| Detection | Presidio with spaCy `en_core_web_lg` (language fixed to `en`) plus regex recognizers: IPv4 0,85, FQDN/HOST 0,6, email 0,9, IBAN 0,8, Luhn card 0,9, deny-list 1,0. Optional GLiNER. | `detectors/engine.py`, `detectors/recognizers.py` |
| Bands | `>= 0,65` auto, `0,35 .. 0,65` gray. CLI `quick_review` drops the gray band, `auto_redact` applies it. | `core/decide.py`, `core/types.py` |
| Residual scan | IPv4 and email regex only, on the written fragments only. Reported, never blocking. | `core/residual.py`, `core/report.py` |
| File types | ~20 text extensions plus docx, xlsx, pptx. Other files are skipped and stay untouched in the root. | `io/registry.py` |
| docx | Body paragraphs and table cell paragraphs. | `io/docx.py` |
| xlsx | String cells that are not formulas. | `io/xlsx.py` |
| pptx | Text frames of top-level slide shapes. | `io/pptx.py` |

### 2.2 Gaps that become leaks when an agent is involved

I ran the detector on a short sample (no files written):

```
HOST  0.6  'os.path.join'
HOST  0.6  'self.name'
NRP   0.85 'cfg.mode'
HOST  0.6  'db01.acme.local'
IP    0.85 '10.1.2.3'
EMAIL 1.0  'john.smith@acme.com'
PERSON 0.85 'Hans Mueller'
```

1. **Hostnames are never anonymized in the CLI default mode.** The FQDN pattern always scores 0,6, which is in the gray band. CLI `quick_review` drops the gray band, so `db01.acme.local` stays in clear text. The residual scan does not look for hostnames either, so the report stays silent.
2. **Source code is damaged in `auto_redact`.** The same FQDN pattern matches `os.path.join` and `self.name`. `cfg.mode` is tagged `NRP` at 0,85 and is replaced even in `quick_review`. For a coding agent this is a quality problem (the agent sees `[HOST_3]` instead of a method call). It round-trips correctly on de-anonymize, but builds and tests in the working copy break.
3. **Office files carry PII outside the processed text.** An agent that unzips a docx (Claude Code's Read tool does not read docx, so agents do this with Python or `unzip`) sees headers, footers, footnotes, comments, tracked changes, text boxes and `docProps/core.xml` (`dc:creator`, `cp:lastModifiedBy`). None of these are processed. The same holds for xlsx sheet names, cell comments, formulas and defined names, and pptx speaker notes, tables, grouped shapes and properties.
4. **File and folder names are not anonymized** (`Hans_Mueller_Vertrag.docx`).
5. **Unsupported files stay in the root.** A `.cs`, `.sql`, `.toml`, `.eml` or `.pdf` file with PII is skipped and remains in the folder the agent works on.
6. **Git history.** If the root is a repository, `.git` still holds every original version, commit authors and messages.
7. **The passphrase is visible to other processes.** `--passphrase` on the command line ends up in shell history and in the process command line. An agent on the same account can read command lines of running processes (for example `Get-CimInstance Win32_Process`).
8. **Plaintext mapping by default.** If the agent can read the mapping file, it has every original value.
9. **Backups are plaintext originals.** They are the most sensitive copy and sit beside the root by default.
10. **De-anonymize in place.** If the user restores the working copy in place while the agent session is still open, the next Read sends real data.
11. **English only.** German names and addresses in German documents are detected less reliably by the English spaCy model.
12. **Scan output contains raw values.** `Candidate.to_dict()` returns `text` and `context`. Any agent-facing API must never return these.

---

## 3. Threat model: how PII can reach the provider

The model provider sees everything Claude Code puts into a request. Anthropic says this directly: "Isolation also does not change what is sent to the model. Your prompts and the files Claude reads are transmitted to the Anthropic API or your configured provider with or without a sandbox." ([sandbox environments](https://code.claude.com/docs/en/sandbox-environments))

| # | Channel | Example |
| - | - | - |
| C1 | Built-in file tools | `Read` of the backup folder or mapping file, `Grep` over the original tree |
| C2 | Shell | `cat`, `type`, `python -c "open(...)"`, `unzip -p x.docx docProps/core.xml` |
| C3 | Running thickanon itself | `thickanon deanon <copy> --mapping <file>`, then reading the result |
| C4 | Secrets in the environment | the passphrase in an env var, shell history, process command lines |
| C5 | Tool output with PII | `git log`, application logs, test fixtures, stack traces, failing commands |
| C6 | MCP servers and connectors | mail, Jira, Drive, database servers returning records |
| C7 | Context loaded without a tool call | CLAUDE.md and rules files, auto memory, git status snapshot at session start, IDE selection, `@file` mentions, MCP server instructions |
| C8 | The user's own prompt | pasting a log or a mail into the prompt |
| C9 | Detector misses inside the anonymized copy | gray-band drops, unprocessed Office parts, file names, unsupported files |
| C10 | Side traffic | `/feedback` and `/bug` transcript upload, session-quality transcript share, telemetry (metrics exclude code and prompts per the docs), WebFetch hostname preflight |
| C11 | Re-identification | the model infers who `[PERSON_1]` is from role, project and dates |

Designs below say which channels they close.

---

## 4. Claude Code mechanisms: what they can and cannot enforce

Verified against the docs on 23.11.2026. Quotes are from the linked pages.

### 4.1 Permission rules (`permissions.allow/ask/deny`)

Source: [permissions](https://code.claude.com/docs/en/permissions)

- Order is fixed: "deny, then ask, then allow. The first match in that order determines the outcome." A managed deny cannot be overridden by any other level.
- `Read(path)` and `Edit(path)` use gitignore syntax. `//path` is absolute, `~/path` is from home, `/path` is relative to the settings source (not the file system root), `path` is relative to the current directory. "On Windows, paths are normalized to POSIX form before matching. `C:\Users\alice` becomes `/c/Users/alice`."
- Coverage of Read deny rules: "Claude makes a best-effort attempt to apply `Read(path)` deny rules to all built-in tools that read files like Grep and Glob." In Bash, they also apply to redirection targets and to "file commands it recognizes, such as `cat`, `head`, `tail`, `sed`, and `tee`".
- **What they do not cover:** "They don't apply to a command that reads files without naming them, such as `grep -r pattern .` run from the directory that holds the file. They also don't apply to arbitrary subprocesses that read or write files indirectly, like a Python or Node script that opens files itself."
- Bash rules match command text. The docs warn: "Bash permission patterns that try to constrain command arguments are fragile" and "A deny rule doesn't match the same program by path or inside `sh -c`". So `Bash(thickanon deanon*)` is friction, not protection (`python -m thickanon deanon ...` passes).
- Built-in read-only commands (`ls`, `cat`, `head`, `grep`, `find`, read-only `git`, ...) "run without a permission prompt in every mode", except where `permissions.blockReadsOutsideWorkingDirectories` applies.
- `permissions.blockReadsOutsideWorkingDirectories: true` makes the file tools refuse reads outside the working directories "in every permission mode, including `bypassPermissions`". `blockWritesOutsideWorkingDirectories` "doesn't limit shell commands, MCP tools, or the programs hooks run".
- `permissions.disableBypassPermissionsMode` and `permissions.disableAutoMode` can be set to `"disable"`.
- `.claudeignore` "has no effect".

**Verdict:** good against the built-in tools (C1) and the obvious shell commands. Not a boundary against C2 or C3 without a sandbox.

### 4.2 Sandbox (`sandbox.*`)

Source: [sandboxing](https://code.claude.com/docs/en/sandboxing)

- "The sandbox runs on macOS, Linux, and WSL2. **On native Windows, Claude Code runs commands unsandboxed.** To use the sandbox on a Windows machine, run Claude Code inside a WSL2 distribution."
- Scope: "Only shell commands and their child processes, meaning Bash, PowerShell, and Monitor." It does not cover Read, Edit, Write, WebFetch, WebSearch, MCP servers, command hooks, status line commands, `apiKeyHelper` or LSP servers.
- Default reads: "Most of the machine". Restrict with `sandbox.filesystem.denyRead` and `allowRead` (narrower path wins). "A `denyRead` entry doesn't stop the Read tool", so pair it with Read deny rules.
- Network: proxy with `network.allowedDomains`, empty by default. No TLS inspection by default. Broad domains enable exfiltration ("domain fronting").
- Escape hatch: Claude may retry with `dangerouslyDisableSandbox`. Turn it off with `sandbox.allowUnsandboxedCommands: false`. `sandbox.failIfUnavailable: true` makes Claude Code exit when the sandbox cannot start.
- Commands typed at the `!` prompt and `excludedCommands` run outside the sandbox.
- `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` strips credentials from all subprocesses.

**Verdict:** on WSL2 this is a real OS boundary for C2 and C3. On native Windows it does not exist.

### 4.3 Hooks

Source: [hooks](https://code.claude.com/docs/en/hooks)

| Event | Can block | Can rewrite | Notes |
| - | - | - | - |
| `UserPromptSubmit` | Yes (`decision: "block"` or exit 2) | **No.** "can't replace the prompt; it only injects `additionalContext` alongside it." | Blocked prompt: "the prompt can still appear in local files such as the session transcript and your prompt history." `suppressOriginalPrompt` hides it from the block message. Default timeout 30 s. |
| `PreToolUse` | Yes (`permissionDecision: "deny"` or exit 2) | Yes, `updatedInput` replaces the whole input. | Hook "allow" does not bypass deny or ask rules. |
| `PostToolUse` | `decision: "block"` does **not** hide the output: "Claude still sees the original output; to replace it, use `updatedToolOutput`." | Yes, `updatedToolOutput` "Replaces the tool's output with the provided value before it is sent to Claude." | **Fails open on a shape mismatch:** "For built-in tools, a value that doesn't match the tool's output schema is ignored and the original output is used." Only the Bash shape (`stdout`, `stderr`, `interrupted`, `isImage`) is documented. Telemetry spans "capture the original output before the hook runs". |
| `PostToolUseFailure` | No | **No.** "can't rewrite a result, so it can't redact a failing command's output." | A failing command is a leak path that `PostToolUse` cannot close. |
| `PostToolBatch` | Yes: "stops the agentic loop before the next model call." | No | Its `tool_response` "contains the same content the model receives". The block message "stays in the conversation", so the reason must not contain PII. |
| `MessageDisplay` | No | Display only. "Claude never sees the replacement." | Not a privacy control. |

Other facts:

- Hook types: `command`, `http`, `mcp_tool`, `prompt`, `agent`. An `http` hook POSTs the JSON input to a URL and reads the same JSON output. A connection failure is a non-blocking error unless `onFailure: "block"` is set (v2.1.295+).
- Hooks from settings run inside subagents too. Command hooks run outside the sandbox with full user rights.
- `allowManagedHooksOnly` in managed settings blocks user, project, local and plugin hooks.
- `updatedToolOutput` "only changes what Claude sees". It does not undo side effects.

**Verdict:** hooks can block prompts and stop the loop. They can replace Bash output reliably. They cannot rewrite prompts, cannot rewrite failed tool output and fail open on other tools if the shape is wrong. They never see C7 context (CLAUDE.md, git status snapshot, memory, IDE context).

### 4.4 Context that never passes a hook (C7)

- Git status snapshot (branch, git user name, recent commit subjects): remove with `CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS=1` ("remove built-in commit and PR workflow instructions and the git status snapshot from Claude's context"). [env vars](https://code.claude.com/docs/en/env-vars)
- CLAUDE.md files: `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` blocks all of them, including user and auto memory files. Auto memory alone: `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`.
- claude.ai connectors (mail, Drive, Jira and similar): `disableClaudeAiConnectors: true`. [settings reference](https://code.claude.com/docs/en/settings-reference)
- `@file` mentions and IDE selection: Read deny rules are applied "best-effort".

### 4.5 MCP servers

Source: [mcp](https://code.claude.com/docs/en/mcp), [managed settings](https://code.claude.com/docs/en/managed-settings)

- Local stdio servers run as normal processes with full user rights. They are not sandboxed.
- Tool permission names are `mcp__<server>__<tool>`. Deny one with a permission rule.
- Admins can lock servers with `allowManagedMcpServersOnly`, `allowedMcpServers` and `deniedMcpServers`.
- `PostToolUse` can replace MCP output (`updatedToolOutput`, or `updatedMCPToolOutput`). MCP output is not schema-checked, so replacement cannot fail open on shape.

### 4.6 Subagents

Source: [sub-agents](https://code.claude.com/docs/en/sub-agents)

- Deny rules in settings apply "to the main conversation and to subagents". Subagents use the same sandbox.
- A `tools` list is not a boundary. The docs' own example: "The subagent has no Edit, Write, or MCP tools but can still change files through Bash."
- Subagent requests go to the same provider. Nothing in the docs suggests a subagent is a privacy boundary.

### 4.7 Managed settings

- File on Windows: `C:\Program Files\ClaudeCode\managed-settings.json` (plus `managed-settings.d\*.json` and `managed-mcp.json`). The legacy `C:\ProgramData\ClaudeCode\` path is not read. [managed settings](https://code.claude.com/docs/en/managed-settings)
- Locks the user cannot loosen: deny rules, `allowManagedPermissionRulesOnly`, `allowManagedHooksOnly`, `disableBypassPermissionsMode`, `allowedProviders`.
- On a single-user machine where the user is also admin, managed settings protect against the agent changing its own configuration. The sandbox already "denies writes to files such as `.claude/settings*.json`" on supported platforms. On native Windows only the permission system protects those files.

### 4.8 Containers, WSL2, VMs

Source: [sandbox environments](https://code.claude.com/docs/en/sandbox-environments), [devcontainer](https://code.claude.com/docs/en/devcontainer)

- "The sandbox runtime and your own container or VM put the whole Claude Code process inside the isolation boundary, so file tools, MCP servers, and hooks are restricted too."
- For native Windows the docs recommend "A container or VM, or run the Bash sandbox inside WSL2".
- The reference dev container has a default-deny iptables firewall. It is "a convention rather than an enforcement boundary, because Claude Code does not require a container".
- "Any approach that allows network egress can still leak data the agent can read."

### 4.9 LLM gateway (`ANTHROPIC_BASE_URL`)

Source: [llm-gateway](https://code.claude.com/docs/en/llm-gateway), [gateway protocol](https://code.claude.com/docs/en/llm-gateway-protocol)

- `ANTHROPIC_BASE_URL` routes inference to `/v1/messages?beta=true` and optionally `/v1/messages/count_tokens`.
- Streaming: Claude Code reads SSE event by event. Buffering the whole response stalls it. It needs the full sequence through `message_delta` and `message_stop`. The `ping` events keep the idle watchdog alive.
- Anthropic's position on rewriting: "A gateway that rewrites or redacts request bodies for content inspection breaks the pairing the same way stripping does, so inspect without modifying." Rewriting content is therefore outside what Anthropic supports.
- `allowedProviders: ["customEndpoint"]` in managed settings pins the base URL. Claude Code then refuses sessions pointed anywhere else.
- The attribution block in `system` must stay first and unchanged.
- Thinking signatures: if the upstream rejects a signature, Claude Code removes earlier thinking blocks and retries. A proxy that edits thinking text triggers this path.
- Fine-grained tool streaming is off by default behind a custom base URL, so tool input arrives as `input_json_delta` chunks of a normal size.

### 4.10 Side traffic (C10)

Source: [data usage](https://code.claude.com/docs/en/data-usage)

- `/feedback`, `/bug` and `/share` send "a copy of your conversation history including code". Turn off with `DISABLE_FEEDBACK_COMMAND=1` or `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`.
- Metrics "never include your code, prompts, or file paths". Error reports redact known patterns.
- The WebFetch preflight sends the hostname to `api.anthropic.com` regardless of provider.
- Local transcripts are stored in plaintext under `~/.claude/projects/` for 30 days (`cleanupPeriodDays`). They stay local, but they hold whatever the session saw.

---

## 5. Designs, from simplest to strongest

Each design lists what it protects, what it does not, the effort in this codebase and the residual risk. Effort is a rough estimate in person-days (PD).

### Design A: documented workflow with a separate working copy, deny rules and (on WSL2) the sandbox

**Idea.** Never point the agent at the real folder. Use a fixed layout:

```
C:\Data\thickanon-vault\        <- agent must never see this
    originals\<project>\          (untouched originals or the backup)
    keys\<project>.map            (encrypted mapping)
C:\Work\agent\<project>\        <- anonymized working copy; start Claude Code here
C:\Work\restored\<project>\     <- de-anonymized result, written by the user
```

**Procedure.**

1. Copy the source folder to `C:\Work\agent\<project>\`. Do not copy `.git`. Remove unsupported file types.
2. Run thickanon on the copy, with `--mode auto_redact`, a deny-list for customer names and internal domains, a passphrase and the mapping in the vault.
3. Read the report. Stop if `RESIDUAL LEAKS FLAGGED` shows or if files were skipped.
4. Open the copy in a new terminal that has no thickanon passphrase in its environment. Start Claude Code in the copy.
5. When the agent is done, close the session. Copy the result to `C:\Work\restored\<project>\` and run `thickanon deanon` on that copy, outside any agent session.

**Project settings** (`C:\Work\agent\<project>\.claude\settings.json`). The keys below are documented. Check them with `/status` and `/permissions` after start.

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "disableBypassPermissionsMode": "disable",
    "blockReadsOutsideWorkingDirectories": true,
    "blockWritesOutsideWorkingDirectories": true,
    "deny": [
      "Read(//c/Data/thickanon-vault/**)",
      "Edit(//c/Data/thickanon-vault/**)",
      "Read(//**/*.thickanon-mapping.json)",
      "Read(//**/*.thickanon-backup/**)",
      "Read(//c/Work/restored/**)",
      "Bash(thickanon deanon*)",
      "Bash(*thickAnonymizer.exe* deanon*)",
      "PowerShell(thickanon deanon*)",
      "PowerShell(*thickAnonymizer.exe* deanon*)",
      "Bash(git log*)",
      "WebFetch",
      "WebSearch"
    ]
  },
  "disableClaudeAiConnectors": true,
  "env": {
    "CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "DISABLE_FEEDBACK_COMMAND": "1"
  }
}
```

Notes on the snippet:

- `Bash(git log*)` is only useful when the copy has a fresh repository. Remove it otherwise if it gets in the way.
- Set the three `env` values in the shell too before you start `claude`. Then they hold even if a value in `env` is read too late at startup (I did not verify the startup order for `CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS`).
- `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` is optional. It also removes the user-level CLAUDE.md, which can hold the user's name, employer and mail address.
- A user-level CLAUDE.md, memory files and MCP servers from `~/.claude.json` still load. Check `/mcp` and `/memory` before work starts.

**Sandbox addition for WSL2 only** (same file, project scope so that `"."` means the project):

```json
{
  "sandbox": {
    "enabled": true,
    "failIfUnavailable": true,
    "allowUnsandboxedCommands": false,
    "filesystem": {
      "denyRead": ["~/", "/mnt/c/Data/thickanon-vault"],
      "allowRead": ["."]
    },
    "network": {
      "allowedDomains": []
    }
  }
}
```

**Protects:** C1 in all cases. C2 and C3 on WSL2 with the sandbox. C7 partly (git snapshot, connectors). C10.
**Does not protect:** on native Windows, any script the agent writes can read the vault (C2, C3). MCP servers (C6). Detector misses in the copy (C9). The user's own prompt (C8). C11.
**Effort:** 0,5 PD for a written guide plus a settings template. No code change. Better after Design B, which automates steps 1 to 3 and 5.
**Residual risk:** medium on native Windows (relies on the agent not working around rules, which a prompt injection in a document can cause). Low to medium on WSL2.

### Design B: thickanon "agent mode": safe export and import, plus an MCP server without de-anonymize

**B1: CLI export and import.** Two new subcommands. The user runs them. The agent never does.

```
thickanon agent-export <src> --workspace C:\Work\agent\<project> --vault C:\Data\thickanon-vault\<project>
    [--deny-file terms.txt] [--mode auto_redact] [--passphrase-file <path> | prompt]
thickanon agent-import C:\Work\agent\<project> --vault C:\Data\thickanon-vault\<project>
    --output C:\Work\restored\<project>
```

`agent-export` does this and fails with a non-zero exit code when a check fails:

1. Refuses a plaintext mapping. Reads the passphrase with `getpass` or from a file, never from `argv`.
2. Refuses a workspace inside the source or the vault (reuse `ensure_output_outside_root`).
3. Copies only supported files. Lists all others and refuses to continue unless `--drop-unsupported` is given. Never copies `.git`. Optional: `git init` with a neutral identity.
4. Anonymizes file and folder names (new `FILENAME` tokens in the same mapping).
5. Writes into the workspace through the existing `apply_scan(output_root=...)` path. Originals are never touched, so no backup is needed in the workspace.
6. Runs a **strict residual scan** over the result: the full regex set from `detectors/recognizers.py` (IPv4, FQDN, email, IBAN, card) plus the deny-list plus a second `detect()` pass. Any finding fails the export.
7. Strips or anonymizes Office metadata and parts the handlers do not cover today (core properties, headers, footers, comments, notes), or refuses such files.
8. Writes a manifest (hash of each exported file) into the vault, so `agent-import` can show which files the agent changed or added.

`agent-import` copies the workspace to `--output` and de-anonymizes there. It reports unknown tokens (already supported by `DeanonReport`) and files that are new since the export.

**B2: MCP server `thickanon-mcp` without de-anonymize.** Optional. It lets the agent check its own text before it writes, for example a mail draft or a log excerpt that the user pasted into a file. Tools:

| Tool | Input | Output | Never returns |
| - | - | - | - |
| `pii_check` | `text` | `{found: bool, counts_by_type}` | values, context snippets |
| `pii_anonymize_text` | `text` | text with tokens, from the *same* mapping | the mapping |
| `workspace_scan` | relative path inside the workspace | counts per file and type | values |

The server holds the vault path and the passphrase in its own process (started by the user, for example as a local HTTP MCP server, so that the passphrase is not in `.mcp.json` or the agent's environment). It has no `deanonymize` tool. Reuse `detectors.engine.detect`, `core.anonymize.apply_tokens`, `core.mapping.MappingStore` and `core.plan.scan_paths`, but never `Candidate.to_dict()` because that returns raw text.

Hard limit: an MCP server cannot stop the agent from reading files. B2 is a helper, not a control.

**Protects:** C3 and C4 (no passphrase or plaintext mapping in the agent's reach, even on native Windows, as long as the vault is unreadable or the mapping is encrypted with a passphrase the agent never sees). Most of C9 (strict scan, file names, metadata, unsupported files, no git history).
**Does not protect:** the vault's `originals` folder on native Windows (still readable by a script unless Design E is used). C5 to C8. C11.
**Effort:** B1 about 4 to 6 PD (CLI wiring 1 PD, passphrase input 0,5 PD, strict residual scan 1 PD, file names 1 PD, Office metadata 1,5 to 2 PD, tests). B2 about 2 PD on top (Python `mcp` SDK, three tools, tests).
**Residual risk:** low for C3 and C4. The `originals` copy is the remaining hot spot, which Design E closes.

### Design C: detector hooks as a tripwire (UserPromptSubmit, PreToolUse, PostToolUse, PostToolBatch)

**Idea.** A local thickanon daemon loads the detector once and answers Claude Code `http` hooks on `127.0.0.1`. Hooks run on every prompt, every tool call and every tool batch.

| Event | Daemon action |
| - | - |
| `UserPromptSubmit` | Run `detect()` on `prompt`. If PII is found, block with counts only. The user anonymizes the text and sends it again. |
| `PreToolUse` | Deny paths inside the vault, deny any command that names `deanon`, the mapping or the vault, deny reading `.docx/.xlsx/.pptx` from outside the workspace. Text matching only (a second net under the deny rules). |
| `PostToolUse` | Run `detect()` on `tool_response`. For `Bash`, return `updatedToolOutput` with the values replaced by tokens from the same mapping. For MCP tools, return `updatedToolOutput` with the redacted text. For any other built-in tool, do not try to rewrite (the shape is not documented and a wrong shape fails open). Mark the batch as tainted. |
| `PostToolBatch` | If any `tool_response` in the batch still holds PII (this also covers failed calls, which `PostToolUse` cannot rewrite), return `decision: "block"`. That "stops the agentic loop before the next model call". |

**Settings** (project or user level; needs Claude Code 2.1.295+ for `onFailure`):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "http", "url": "http://127.0.0.1:7341/hook", "timeout": 30, "onFailure": "block" } ] }
    ],
    "PreToolUse": [
      { "matcher": "*", "hooks": [ { "type": "http", "url": "http://127.0.0.1:7341/hook", "timeout": 30, "onFailure": "block" } ] }
    ],
    "PostToolUse": [
      { "matcher": "*", "hooks": [ { "type": "http", "url": "http://127.0.0.1:7341/hook", "timeout": 60 } ] }
    ],
    "PostToolBatch": [
      { "hooks": [ { "type": "http", "url": "http://127.0.0.1:7341/hook", "timeout": 60, "onFailure": "block" } ] }
    ]
  }
}
```

**Daemon responses** (JSON bodies the daemon returns with HTTP 200):

Block a prompt (the reason is shown to the user, not to Claude):

```json
{
  "decision": "block",
  "reason": "thickanon: prompt contains PII (PERSON x2, EMAIL x1). Anonymize it and send again.",
  "hookSpecificOutput": { "hookEventName": "UserPromptSubmit", "suppressOriginalPrompt": true }
}
```

Deny a tool call:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "thickanon: access to the vault or to de-anonymize is not allowed in agent sessions."
  }
}
```

Replace Bash output (documented shape):

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "updatedToolOutput": {
      "stdout": "commit by [PERSON_4] <[EMAIL_2]> ...",
      "stderr": "",
      "interrupted": false,
      "isImage": false
    }
  }
}
```

Stop the loop (this text stays in the conversation, so it must hold no values):

```json
{
  "decision": "block",
  "reason": "thickanon: a tool result in this batch contains PII (PERSON x3). The turn was stopped before it was sent."
}
```

**Daemon sketch** (stdlib HTTP server around the existing core; error handling and auth left out):

```python
# thickanon/agent/hookd.py  (proposed module)
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from thickanon.core.types import AnonymizeConfig, ReviewMode
from thickanon.detectors.engine import detect
from thickanon.core.anonymize import apply_tokens

CFG = AnonymizeConfig(mode=ReviewMode.AUTO_REDACT)

def counts(entities):
    out = {}
    for e in entities:
        out[e.entity_type] = out.get(e.entity_type, 0) + 1
    return ", ".join(f"{k} x{v}" for k, v in sorted(out.items()))

def handle(event, mapping):
    name = event["hook_event_name"]
    if name == "UserPromptSubmit":
        found = detect(event.get("prompt", ""), CFG)
        if found:
            return {"decision": "block",
                    "reason": f"thickanon: prompt contains PII ({counts(found)}).",
                    "hookSpecificOutput": {"hookEventName": name, "suppressOriginalPrompt": True}}
    elif name == "PostToolUse" and event.get("tool_name") == "Bash":
        resp = event.get("tool_response") or {}
        out = resp.get("stdout", "")
        found = detect(out, CFG)
        if found:
            return {"hookSpecificOutput": {"hookEventName": name, "updatedToolOutput": {
                "stdout": apply_tokens(out, found, mapping),
                "stderr": "", "interrupted": bool(resp.get("interrupted")), "isImage": False}}}
    elif name == "PostToolBatch":
        for call in event.get("tool_calls", []):
            body = call.get("tool_response")
            text = body if isinstance(body, str) else json.dumps(body)
            found = detect(text, CFG)
            if found:
                return {"decision": "block",
                        "reason": f"thickanon: tool result holds PII ({counts(found)}). Turn stopped."}
    return {}
```

Open points in the sketch: `stderr` of Bash must be scanned too; `PostToolBatch` sees the result *after* any `PostToolUse` replacement only if Claude Code applies it first (the docs say `tool_response` "contains the same content the model receives", which suggests yes, but test it); the mapping update needs a lock; the daemon must bind to `127.0.0.1` only and check a shared secret header (`headers` plus `allowedEnvVars`).

**Important limits.**

- **Blocking is not the same as never sending.** After a `PostToolBatch` block the tool result is still in the conversation. If the user types "continue", it goes out with the next request. The user must discard that part of the conversation (rewind or start a new session). I did not verify how `/rewind` treats a stopped batch. Test this before relying on it.
- The detector is the limit. A hook that misses a name lets it through. Gray-band detections must be treated as hits here (`auto_redact` semantics).
- Latency: spaCy on 4.000-character windows takes tens to hundreds of milliseconds per call. Large tool results (a full log) can take seconds. GLiNER is slower. A daemon is required. A `command` hook that loads the model per call is too slow.
- False positives stop work. The FQDN pattern hits `os.path.join`, so on code the tripwire fires constantly until the HOST recognizer is fixed (section 6, item 7).
- Hooks never see C7 context. They do not see the subagent's own prompts directly, but they fire on the subagent's tool calls.
- A command hook or the daemon runs with full user rights. Keep the daemon small.
- Project hooks run only after workspace trust. Put the hooks in user settings or managed settings with `allowManagedHooksOnly` so that a repository cannot remove them.

**Protects:** C5, C6 (MCP output can be replaced), C8 (block only), part of C9 (a second detection pass on what the agent actually reads). Adds a second net for C1 to C3.
**Does not protect:** C7. Anything the detector misses. Failed tool output except by stopping the loop. Telemetry spans if OpenTelemetry is configured.
**Effort:** 3 to 5 PD (daemon 1,5 PD, event handling and tests 1,5 PD, settings template and install 0,5 PD, latency tuning 1 PD).
**Residual risk:** medium. Good as a tripwire and for logs, weak as the only control.

### Design D: rewriting proxy at `ANTHROPIC_BASE_URL`

**Idea.** A local proxy sits between Claude Code and the API. It anonymizes every request body and de-anonymizes every response. The model only ever sees tokens. Claude Code, the tools and the local files see real values.

```
Claude Code --(real values)--> thickanon-proxy 127.0.0.1:8787 --(tokens)--> api.anthropic.com
            <--(real values)--                                 <--(tokens)--
```

**Configuration.**

```powershell
$env:ANTHROPIC_BASE_URL = "http://127.0.0.1:8787"
$env:ANTHROPIC_API_KEY  = "dummy-local-key"   # the proxy holds the real key
claude
```

With managed settings, pin it so the agent cannot start a session that bypasses the proxy:

```json
{
  "allowedProviders": ["customEndpoint"],
  "env": { "ANTHROPIC_BASE_URL": "http://127.0.0.1:8787" }
}
```

The real API key lives only in the proxy process. Then the agent cannot call `api.anthropic.com` directly with a key it does not have. With a claude.ai subscription login this does not hold: the OAuth token stays on the machine and the proxy must forward `Authorization` (per the gateway guide). The agent could then use the token directly unless the token file is unreadable (Design E).

**What the proxy must do.**

1. **Endpoints.** `POST /v1/messages` and `POST /v1/messages/count_tokens` both carry content, so anonymize both. Reject every other path that carries a body (fail closed).
2. **Request walk.** For each `system` text block (but keep the first attribution block byte-for-byte), each `messages[].content` block of type `text`, each `tool_result` (string or nested blocks), and each `tool_use.input` (strings inside the JSON, because Claude Code sends back the de-anonymized inputs it executed): run `detect()` plus deny-list, replace with `MappingStore.token_for()`. Also check `tools[].description` (MCP descriptions can hold names).
3. **Do not touch** `thinking` and `redacted_thinking` blocks. They carry signatures. The model produced them from tokens, so they contain tokens only, unless the proxy de-anonymized them on the way back. Pass thinking through unchanged in both directions.
4. **Images and documents.** The proxy cannot anonymize an image or a PDF. Block them or drop them with a notice.
5. **Response stream.** Pass SSE events through as they arrive (buffering stalls Claude Code). Keep `ping` events.
   - `text_delta`: hold back text from an opening `[` until the token closes or 40 characters pass, then emit with tokens replaced. Tokens split across deltas (`"[PER"`, `"SON_1]"`) are the normal case, not an edge case.
   - `input_json_delta`: collect the `partial_json` of the content block until `content_block_stop`, parse it, replace tokens inside string values, re-serialize and emit as one delta. Raw text replacement inside JSON is wrong because real values can contain `"` or `\`.
   - Pass `message_start`, `message_delta`, `message_stop` and error bodies unchanged.
6. **One mapping.** The proxy loads the same encrypted mapping as the exported files (passphrase typed into the proxy console, never into the agent). New entities seen in chat get new tokens and are saved, so file tokens and chat tokens agree.
7. **Determinism for prompt caching.** Anonymize each content block on its own with a fixed configuration. The same block then produces the same bytes on every turn, so the cached prefix stays stable.

**Why it is attractive.** It covers C1 to C10 for the content channel in one place: CLAUDE.md, git snapshot, MCP output, failed tool output, subagents, compaction and auto-mode classifier requests all pass through `/v1/messages`. False positives such as `os.path.join` also round-trip, because the model's `[HOST_3]` is turned back into `os.path.join` before Claude Code runs the edit.

**Why it is risky.**

- Anthropic's gateway guide says "inspect without modifying". Rewriting is unsupported. New request fields or block types in a later Claude Code release can pass the walker unseen (leak) or break requests. The walker must reject unknown block types instead of passing them.
- The detector runs on every turn over the whole new content. A name missed in one turn leaks in that turn, even if it was caught before. This is the same recall limit as every design, but now in real time with no human review.
- The model reasons on tokens. Questions such as "is `[IP_1]` in the same subnet as `[IP_2]`" or "sort these people by surname" lose meaning.
- Streaming correctness: token boundaries, JSON re-serialization and error paths. A bug shows up as a broken session, not as a leak, if the code fails closed.
- WebSearch queries come from the model (tokens only, so no leak), but search results with tokens in them are meaningless. The WebFetch preflight still sends hostnames to `api.anthropic.com` (only the hostname).
- Local transcripts hold real values (as they do without the proxy).

**Reuse.** `detectors.engine.detect`, `core.mapping.MappingStore`, `core.anonymize.apply_tokens` and `deanonymize_counted`, `core.residual` (as a final regex net on the outbound body). New: an async HTTP proxy (for example `aiohttp` or `httpx` with Starlette), the SSE rewriter and the request walker.

**Alternative to building it.** LiteLLM's proxy has a Presidio-based PII masking guardrail with an option to unmask output. I did not verify whether it handles the Anthropic `/v1/messages` pass-through, `tool_use` input JSON and streaming the way Claude Code needs. Evaluate it before writing a new proxy. It would not reuse the thickanon mapping without custom code, so tokens in files and in chat would not match.

**Effort:** 10 to 15 PD for a robust prototype with tests against recorded Claude Code traffic. Ongoing maintenance with each Claude Code release.
**Residual risk:** medium. Wide coverage, but fragile and unsupported. Still bounded by detector recall.

### Design E: run the agent in a container or WSL2 that only sees the anonymized copy

**Idea.** Put a hard OS boundary around the whole Claude Code process. The originals, the backup, the mapping, the passphrase, the user's mail and the rest of the disk are not inside. The agent cannot read what is not there.

**Options on this Windows 11 machine.**

1. **WSL2 distribution** dedicated to agent work. Copy (do not mount) the exported workspace into the Linux file system, or mount only `C:\Work\agent\<project>`. Turn on the built-in sandbox (it works on WSL2). Block access to `/mnt/c` with the sandbox `denyRead` and keep in mind that the file tools are not sandboxed, so also add Read deny rules for `//mnt/c/**`. Disable Windows interop for this distribution (`[interop] enabled=false` in `/etc/wsl.conf`) so that sandboxed commands cannot launch Windows binaries. The docs explain how WSL2 hands Windows binary launches to the host over a Unix socket.
2. **Dev container** (Docker Desktop with the WSL2 backend), based on Anthropic's reference container with its default-deny firewall. Mount only the workspace. Allow egress to `api.anthropic.com` (plus `claude.ai` and `platform.claude.com` for OAuth sign-in, or neither when an API key is used).
3. **Docker Sandboxes** (microVM) or a small Hyper-V VM, if kernel separation is required.

**Container rules.**

- Mount only `C:\Work\agent\<project>` read-write. Never mount the vault, the user profile, `~/.claude` of the host or `~/.ssh`.
- No thickanon mapping and no passphrase inside. thickanon itself (for B2 or C) may run inside without a vault, or the hook daemon runs on the host and the container reaches it through one allowed port.
- Fresh `git init` inside with a neutral identity (`agent` / `agent@localhost`).
- No user-level CLAUDE.md, no memory files, no MCP servers except the ones listed in the container image.
- Egress allowlist only. Everything else is denied. This also stops exfiltration of the workspace to other hosts, which matters if a document contains a prompt injection.
- The user runs `thickanon agent-import` on the host after the session.

**Protects:** C1 to C4 fully (nothing to read). C6 and C7 (only what the image contains). C10 with the env settings from Design A.
**Does not protect:** C9 (the copy itself may still contain PII the detector missed). C5 for data that is part of the copy (logs, fixtures). C8. C11.
**Effort:** 2 to 3 PD (container or WSL2 recipe, firewall allowlist, launch script, mount check, guide). No change in thickanon besides Design B.
**Residual risk:** low for access to originals and secrets. The remaining risk is only what is inside the exported copy, which is exactly what thickanon's report and strict scan are for.

---

## 6. thickanon changes needed (backlog, in priority order)

| # | Change | Why | Where | Size |
| - | - | - | - | - |
| 1 | `anonymize --output <dir>` on the CLI | Never edit originals for agent work | `cli.py`, reuse `apply_scan(output_root=...)` and `ensure_output_outside_root` | S |
| 2 | `deanonymize --output <dir>` | Never restore inside the agent workspace | `core/orchestrator.py` `deanonymize_paths`, `cli.py` | S |
| 3 | Passphrase by prompt (`getpass`), `--passphrase-file` or `--passphrase-env`; warn on `--passphrase` | Keep it out of history and process lists | `cli.py` | S |
| 4 | `agent-export` / `agent-import` (Design B1) | One safe, repeatable path | new `core/agent.py`, `cli.py` | M |
| 5 | Strict residual scan: all regex recognizers plus deny-list plus a second `detect()`; non-zero exit on findings | Today only IPv4 and email are checked and only reported | `core/residual.py`, `core/report.py` | S to M |
| 6 | Office coverage: docx headers, footers, footnotes, comments, core properties; xlsx sheet names, comments, defined names, properties; pptx notes, tables, group shapes, properties. Or a `--strip-metadata` option | Agents read raw OOXML | `io/docx.py`, `io/xlsx.py`, `io/pptx.py` | M |
| 7 | HOST recognizer for code: require a known TLD list or an internal-suffix list from the deny-list; do not match `identifier.identifier` in code files; review `NRP` hits on dotted identifiers | Today hostnames are dropped in CLI default mode and code is damaged in `auto_redact` | `detectors/recognizers.py`, `detectors/engine.py` | M |
| 8 | File and folder name anonymization | Names leak through paths | `core/plan.py`, new token type | M |
| 9 | Policy for unsupported files: list and refuse in agent mode | They stay in the root with PII | `core/plan.py`, `io/registry.py` | S |
| 10 | German detection (`de_core_news_lg`) or GLiNER multi by default for German text | Customer documents are often German | `core/types.py` `language`, `detectors/engine.py` | M |
| 11 | `thickanon check` (stdin to exit code plus counts, never values) and `thickanon serve-hooks` (Design C daemon) | Hooks and CI | new `agent/` package | M |
| 12 | MCP server without de-anonymize (Design B2) | Agent self-check | new `agent/mcp_server.py` | M |
| 13 | Make the mapping passphrase mandatory for `agent-export`, keep plaintext default only for the desktop flow | Mapping is the key | `core/mapping.py`, `cli.py` | S |

S = up to 1 PD, M = 1 to 3 PD.

---

## 7. Other agents

**GitHub Copilot coding agent (cloud).** It runs in a GitHub Actions environment on the repository content and works through pull requests. Push only the exported workspace to a separate private repository. Never push the original repository. GitHub's docs describe the agent firewall as protection "for common scenarios" that "should not be considered a comprehensive security solution". Content exclusion is not a reliable control for agents: GitHub's docs state that Copilot CLI and IDE agent mode did not support content exclusion. A GitHub changelog from 02.09.2026 says the Copilot app and CLI now respect it. The status for IDE agent mode and the cloud agent is unclear from the sources I found. Design E applies directly (the cloud runner only has the exported repository). Designs C and D do not apply (no hooks into its model traffic that I could verify).

**GitHub Copilot agent mode in VS Code (local).** Same exposure as Claude Code on the host: it can run terminal commands. Use Design E (VS Code dev container with only the workspace mounted).

**OpenAI Codex CLI.** It has sandbox modes `read-only` and `workspace-write` (network off by default in `workspace-write`) and a native Windows sandbox. I did not verify how far Codex restricts *reads* outside the workspace. Assume reads are not restricted and use Design E. Codex supports custom model providers in `config.toml`, so Design D may work in principle, but I did not verify the request format details.

**General rule for any agent:** the only control that does not depend on the agent's own features is Design E (it sees only the anonymized copy) plus Design B (the copy is clean). Hooks and proxies are agent-specific additions.

---

## 8. Recommended phased plan

**Phase 0: now, no code (0,5 PD).**

1. Write the guide for Design A and the settings template.
2. Always use `--mode auto_redact`, a deny-list with customer names and internal domains, and a passphrase.
3. Never start an agent in a folder that contains, or sits beside, the mapping or the backup.
4. For code projects, review hostnames by hand after the run, because CLI `quick_review` does not anonymize them.

**Phase 1: safe export and import (5 to 7 PD).** Backlog items 1, 2, 3, 4, 5, 9 and 13. Result: one command creates a clean workspace and one command restores the result into a separate folder. The passphrase never appears on a command line.

**Phase 2: isolation (2 to 3 PD).** Design E with a WSL2 distribution or a dev container, a launch script that mounts only the workspace, and an egress allowlist. Turn on the Claude Code sandbox inside WSL2 as a second layer. From here on, the originals and the key are physically out of reach.

**Phase 3: detection quality (4 to 6 PD).** Backlog items 6, 7, 8 and 10. This reduces C9, the risk that remains after Phase 2.

**Phase 4: tripwire (3 to 5 PD).** Design C with the `serve-hooks` daemon, installed in user settings (or managed settings with `allowManagedHooksOnly`). Optional Design B2 MCP server. First test how a stopped batch can be removed from the conversation.

**Phase 5: evaluate the proxy (spike 3 PD, full build 10 to 15 PD).** Only if the users need to paste live PII into chat and still want useful answers. Evaluate LiteLLM's Presidio guardrail first. Build the thickanon proxy only if the evaluation shows a clear gap and the maintenance cost is accepted.

**Exit criteria for each phase:** a seeded test folder (names, German addresses, internal FQDNs, IPs, docx with author property, header and comment, xlsx with sheet name, a `.git` history, a log file) produces zero clear-text hits in (a) the workspace, (b) a recorded `/v1/messages` body captured with a pass-through logging proxy during a scripted agent session.

---

## 9. Points I could not verify

- The exact `tool_response` shapes for Read, Grep, Glob, Edit and WebFetch in `PostToolUse`. Only the Bash shape is documented. Log real events before writing `updatedToolOutput` for other tools.
- Whether `PostToolBatch` sees the output after `PostToolUse` replaced it.
- How `/rewind` or other commands remove a tool result after a `PostToolBatch` block.
- Whether `CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS` takes effect when set only in the `env` block of project settings (set it in the shell as well).
- LiteLLM Presidio guardrail behaviour with Claude Code traffic.
- Codex CLI read restrictions and custom provider request details.
- Copilot content exclusion status for IDE agent mode and the cloud agent.

---

## 10. Sources

Claude Code documentation (read 23.11.2026):

- Permissions: https://code.claude.com/docs/en/permissions
- Sandboxing: https://code.claude.com/docs/en/sandboxing
- Sandbox environments: https://code.claude.com/docs/en/sandbox-environments
- Dev container: https://code.claude.com/docs/en/devcontainer
- Hooks reference: https://code.claude.com/docs/en/hooks
- Subagents: https://code.claude.com/docs/en/sub-agents
- MCP: https://code.claude.com/docs/en/mcp
- Managed settings: https://code.claude.com/docs/en/managed-settings
- Settings reference: https://code.claude.com/docs/en/settings-reference
- Environment variables: https://code.claude.com/docs/en/env-vars
- LLM gateways: https://code.claude.com/docs/en/llm-gateway
- Gateway compatibility guide: https://code.claude.com/docs/en/llm-gateway-protocol
- Data usage: https://code.claude.com/docs/en/data-usage

Other agents:

- Codex sandboxing: https://developers.openai.com/codex/concepts/sandboxing
- Codex on Windows: https://developers.openai.com/codex/windows
- Copilot agent firewall: https://docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/customize-the-agent-firewall
- Copilot content exclusion: https://docs.github.com/en/copilot/concepts/context/content-exclusion
- Copilot changelog 02.09.2026: https://github.blog/changelog/2026-09-02-content-exclusions-generally-available-in-copilot-app-and-cli

thickanon code read: `README.md`, `src/thickanon/cli.py`, `src/thickanon/core/*.py`, `src/thickanon/detectors/engine.py`, `src/thickanon/detectors/recognizers.py`, `src/thickanon/io/*.py`, `src/thickanon/ui/api.py` (grep only), `docs/superpowers/specs/*.md`.
