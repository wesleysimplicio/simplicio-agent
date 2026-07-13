# Adding a CLI Command to simplicio-runtime

Canonical pattern for wiring a new top-level CLI command (e.g. `simplicio discord`)
into the 84K-line `main.rs` monofile. Reuse existing tool modules to avoid
rewriting API clients.

## Anatomy of a new command

Every CLI command needs changes in **4 files**:

| # | File | Change |
|---|------|--------|
| 1 | `src/main.rs` — dispatch table | Add match arm (~1 line) |
| 2 | `src/main.rs` — command function | Add `fn command_name()` (~80-280 lines) |
| 3 | `src/command_registry.rs` | Add `CommandEntry` (description, aliases, category) |
| 4 | `COMMAND_DISPATCH_MAP.md` | Add table row (optional — generated, but keep in sync) |

Optional: help text in main.rs if a `help()` or `print_commands()` function exists.

## Step-by-step

### 1. Dispatch entry (`src/main.rs`, `fn dispatch()`)

Insert a new match arm near related commands. Pattern:

```rust
"command-name" | "alias" => command_fn(resolve_config(args)?),
```

Example (from adding `discord` next to `telegram`):

```rust
"telegram" | "tg" => telegram(resolve_config(args)?),
"discord" | "dc" => discord(resolve_config(args)?),
```

### 2. Command function (`src/main.rs` ~77000-79000 range)

Place the function near similar commands (telegram, channel, etc.). Pattern:

```rust
fn unconfigured_msg() -> String { /* env var names */ }

fn print_result(config: &RuntimeConfig, action: &str, result: &Result<String, String>) {
    // config.json ? json output : human output
}

fn command_name(config: RuntimeConfig) -> Result<(), String> {
    let task = task_text(&config);
    let sub = task.split_whitespace().next().unwrap_or("status").to_string();
    let rest = task.split_once(char::is_whitespace)
        .map(|p| p.1).unwrap_or("").trim().to_string();
    let configured = config_fn();

    match sub.as_str() {
        "action1" => { /* ... */ }
        "action2" => { /* ... */ }
        _ => { /* default: status / help */ }
    }
}
```

**Key helpers already available** (no import needed — same file):
- `task_text(&config)` — extracts CLI args from `RuntimeConfig`
- `resolve_config(args)?` — builds `RuntimeConfig` from dispatch args
- `discord_config()` / `telegram_config()` — env-var readers (canonical pattern)
- `channel_send_discord_provider(to, body)` — send via existing provider
- `find_on_path("curl")` — locate system curl
- `run_command_timeout(&curl, &args, Duration)` — run curl wrapper
- `env::var("ENV_VAR")` — read env vars
- `config.json` — boolean flag for JSON vs human output

### 3. Command registry (`src/command_registry.rs`)

Add entry in `build_registry()` under the right category:

```rust
(
    "command-name",
    &["alias1", "alias2"],
    "main::function_name",
    "One-line description shown in help / map output",
    "category",  // e.g. "comms", "core", "memory"
),
```

Categories used: `core`, `memory`, `delivery`, `coding`, `agents`, `security`,
`runtime`, `evidence`, `learning`, `comms`.

### 4. Help text (if a print_commands() exists)

Search for the existing command's help line and add a new one next to it:

```
  simplicio command-name subcommand1 | subcommand2 | status [--json]
```

### 5. Tool modules — reuse, don't rewrite

Before writing API client code, check if a tool module already exists in `src/`:

- `htool_discord_tool.rs` — all Discord REST API actions (guilds, channels, messages, roles, pins, threads)
- `imessage.rs` — iMessage send/receive
- `findmy.rs` — Apple FindMy device tracking
- Various `skill_*.rs` — domain-specific tools

All can be called via their public dispatch functions (e.g.
`htool_discord_tool::htool_discord_tool_dispatch(action, args_json)`).

## Example: adding `discord` command

**Context:** `htool_discord_tool.rs` already had all 15 Discord REST API actions.
`main.rs` already had `discord_config()` and `channel_send_discord_provider()`.
The only missing piece was the CLI wrapper — the `fn discord()` function and
dispatch entry.

**Changes made:**
- 1 line in dispatch table (line 2312)
- ~280 lines command function (line 76938)
- 7 lines in command_registry.rs
- 1 line in help text
- 1 line in COMMAND_DISPATCH_MAP.md
- Plus: `"dc"` alias added to `openclaw_gateway_1577.rs`

**Subcommands supported:**
`send`, `guilds`, `channels`, `messages`, `server-info`, `roles`,
`member-info`, `search-members`, `pins`, `pin`, `unpin`, `delete`,
`thread`, `add-role`, `remove-role`, `status`

## Pitfalls

- **Pre-existing compilation errors:** `inference_pool.rs` and others have
  pre-existing errors (Rust 2015 edition in `async fn`, etc.). They are NOT
  caused by your changes. The lint output will show them but the patch tool
  will report "Pre-existing lint errors" as long as your changes don't add new
  ones.
- **`discord_config()` vs `get_bot_token()`:** `main.rs::discord_config()`
  checks `SIMPLICIO_DISCORD_BOT_TOKEN` then `DISCORD_BOT_TOKEN`.
  `htool_discord_tool::get_bot_token()` only checks `DISCORD_BOT_TOKEN`.
  Prefer the main.rs version for user-facing commands.
- **`channel_send_discord_provider(to, body)`:** Passing empty `to` sends to
  the default configured channel. Passing a channel ID string overrides.
- **JSON output:** Always support `--json` via `config.json`. The JSON schema
  convention: `"schema":"simplicio.<command>/v1"`.
- **alias consistency:** When adding platform aliases (e.g. `"dc"` for discord),
  also update `src/openclaw_gateway_1577.rs` if it has a platform parse function.
