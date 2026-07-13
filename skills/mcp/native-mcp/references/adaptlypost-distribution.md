# AdaptlyPost distribution handoff pattern

Session-specific note for the Consultoria de Imagem SaaS:

- Distribution layer: `AdaptlyPost` at `https://adaptlypost.com/pt`
- Intended integration mode: MCP
- Role in the workflow: Hermes prepares the final asset package; AdaptlyPost handles the final scheduling/publication/distribution step.
- Recommended handoff payload:
  - final video file or video URL
  - final caption/description
  - platform-specific CTA
  - target network(s)
  - campaign/project identifier
  - optional thumbnail and hashtags
- Recommended status loop:
  1. `approved` in review channel
  2. export to `outbox/`
  3. publish via AdaptlyPost MCP tool
  4. write back publication status and link
  5. store result in metrics/logs

Pitfall:
- Do not let distribution become a creative step. Keep it as the last-mile executor only.
