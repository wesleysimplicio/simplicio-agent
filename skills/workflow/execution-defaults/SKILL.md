---
name: execution-defaults
description: Class-level operating defaults for this user's Hermes/Simplicio setup — preferred fast-path service tier, approval bypass baseline, and how to keep the two separate.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  tags: [defaults, approvals, fast-path, yolo, configuration, workflow]
---

# Execution Defaults

Use this skill when configuring or explaining the user's normal operating mode for Hermes/Simplicio.

## Baseline preference

For normal operation, prefer:

- `agent.service_tier: fast`
- `approvals.mode: off` (`--yolo` behavior)

Treat that pairing as the default unless the user explicitly asks for a more conservative setup.

## Important distinction

- **Fast** = service-tier preference
- **YOLO** = approval-bypass preference

They are independent. If you change one, do not imply the other changed automatically.

## Practical configuration

```bash
hermes config set agent.service_tier fast
hermes config set approvals.mode off
```

Per-run override:

```bash
hermes --yolo ...
```

## Reply identity (Wesley)

- If the user states they are on **Hermes original** (e.g. Discord via `~/.hermes`, AlfradHD) or corrects you with **"você é Hermes" / "não confunda"**, treat that as a **hard switch**: you are **Hermes original** in that thread — not Simplicio Agent. Drop Simplicio-first branding unless they explicitly ask about Simplicio.
- If they state **Simplicio Agent** / Simplicio bot, use Simplicio user-facing branding while keeping internal Hermes names in code/config paths.
- Cost questions on **xai-oauth**: cite Hermes `estimated_cost_usd` + `/usage`; do not invent xAI invoice amounts — subscription is outside Hermes metering.

## Pitfalls

- Do not describe Fast as if it were approval bypass.
- Do not describe YOLO as if it changes model quality or service tier.
- If the user asks for the "normal" setup, default to both values above and mention any deviation explicitly.

## Reference

See `references/fast-yolo-operating-defaults.md` for the session-derived rationale and a concise reminder of the preferred baseline.
