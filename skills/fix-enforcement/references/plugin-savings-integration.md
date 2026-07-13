# Plugin Savings Integration

> How the simplicio Hermes plugin appends token-savings summaries to every tool result.

## Pattern

Every tool handler that calls the simplicio binary should append a savings line:

```python
def _handle_simplicio_xxx(args: dict, **kwargs) -> str:
    # 1. Run the command
    result = <actual output>
    
    # 2. Append savings
    repo = args.get("repo", "")
    savings = _extract_savings_summary(repo)
    if savings:
        result = f"{result}\n\n---\n{savings}"
    
    return result
```

## Savings extraction function

```python
def _extract_savings_summary(repo_path: str | None = None) -> str | None:
    """Calls `simplicio savings report --json` and returns a human line.
    
    Returns None when:
    - simplicio binary not found or errors
    - no savings recorded yet (all zeros)
    """
    try:
        cmd_args = ["savings", "report", "--json"]
        if repo_path:
            cmd_args.extend(["--repo", repo_path])
        output = _run_simplicio(cmd_args, repo=repo_path or None)
        data = json.loads(output)
        delta = data.get("delta", {})
        saved = delta.get("paid_tokens_saved", 0)
        local = delta.get("local_tokens_shifted", 0)
        if saved or local:
            return (
                f"Token savings: ~{saved} paid tokens saved, "
                f"{local} run locally via Simplicio"
            )
    except Exception:
        pass
    return None
```

## Tools covered

| Tool | Has savings? | Since |
|------|-------------|-------|
| `simplicio_run` | ✅ Always had | Initial |
| `simplicio_exec` | ✅ Added | 2026-06-16 |
| `simplicio_context` | ✅ Added | 2026-06-16 |

## Runtime side

The simplicio runtime also prints savings to stderr after every command via
`print_savings_summary()` in `savings_analytics.rs`, wired into `main()` after
dispatch. Format: `simplicio: saved ~X tokens (Y%) across Z event(s)`.
