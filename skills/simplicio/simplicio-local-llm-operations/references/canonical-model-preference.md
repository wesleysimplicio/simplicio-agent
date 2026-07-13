# Canonical local model preference

Session note:
- The user explicitly defined the canonical local Simplicio model name as `gemma4:4b-q4_K_M`.

Operational interpretation:
- Treat this as the desired canonical target when describing or configuring the local model.
- If a status probe reports a different currently active model, report that as current state divergence rather than overriding the user-defined canonical choice.

Use this reference when updating the runtime, local model daemon, or any messaging about the default local LLM.