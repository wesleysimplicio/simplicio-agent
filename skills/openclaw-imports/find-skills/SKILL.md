---
name: find-skills
description: Helps users discover and install agent skills when they ask questions like "how do I do X", "find a skill for X", "is there a skill that can...", or express interest in extending capabilities. This skill should be used when the user is looking for functionality that might exist as an installable skill.
---

# Find Skills

This skill helps you discover and install skills from the open agent skills ecosystem.

## When to Use This Skill

Use this skill when the user:

- Asks "how do I do X" where X might be a common task with an existing skill
- Says "find a skill for X" or "is there a skill for X"
- Asks "can you do X" where X is a specialized capability
- Expresses interest in extending agent capabilities
- Wants to search for tools, templates, or workflows
- Mentions they wish they had help with a specific domain (design, testing, deployment, etc.)

## What is the Skills CLI?

The Skills CLI (`npx skills`) is the package manager for the open agent skills ecosystem. Skills are modular packages that extend agent capabilities with specialized knowledge, workflows, and tools.

**Key commands:**

- `npx skills find [query]` - Search for skills interactively or by keyword
- `npx skills add <package>` - Install a skill from GitHub or other sources
- `npx skills check` - Check for skill updates
- `npx skills update` - Update all installed skills

**Browse skills at:** https://skills.sh/

## How to Help Users Find Skills

### Step 1: Understand What They Need

When a user asks for help with something, identify:

1. The domain (e.g., React, testing, design, deployment)
2. The specific task (e.g., writing tests, creating animations, reviewing PRs)
3. Whether this is a common enough task that a skill likely exists

### Step 2: Search for Skills

Run the find command with a relevant query:

```bash
npx skills find [query]
```

For example:

- User asks "how do I make my React app faster?" → `npx skills find react performance`
- User asks "can you help me with PR reviews?" → `npx skills find pr review`
- User asks "I need to create a changelog" → `npx skills find changelog`

The command will return results like:

```
Install with npx skills add <owner/repo@skill>

vercel-labs/agent-skills@vercel-react-best-practices
└ https://skills.sh/vercel-labs/agent-skills/vercel-react-best-practices
```

### Step 3: Present Options to the User

When you find relevant skills, present them to the user with:

1. The skill name and what it does
2. The install command they can run
3. A link to learn more at skills.sh

Example response:

```
I found a skill that might help! The "vercel-react-best-practices" skill provides
React and Next.js performance optimization guidelines from Vercel Engineering.

To install it:
npx skills add vercel-labs/agent-skills@vercel-react-best-practices

Learn more: https://skills.sh/vercel-labs/agent-skills/vercel-react-best-practices
```

### Step 4: Offer to Install

If the user wants to proceed, you can install the skill for them:

```bash
npx skills add <owner/repo@skill> -g -y
```

The `-g` flag installs globally (user-level) and `-y` skips confirmation prompts.

## Common Skill Categories

When searching, consider these common categories:

| Category        | Example Queries                          |
| --------------- | ---------------------------------------- |
| Web Development | react, nextjs, typescript, css, tailwind |
| Testing         | testing, jest, playwright, e2e           |
| DevOps          | deploy, docker, kubernetes, ci-cd        |
| Documentation   | docs, readme, changelog, api-docs        |
| Code Quality    | review, lint, refactor, best-practices   |
| Design          | ui, ux, design-system, accessibility     |
| Productivity    | workflow, automation, git                |

## Tips for Effective Searches

1. **Use specific keywords**: "react testing" is better than just "testing"
2. **Try alternative terms**: If "deploy" doesn't work, try "deployment" or "ci-cd"
3. **Check popular sources**: Many skills come from `vercel-labs/agent-skills` or `ComposioHQ/awesome-claude-skills`

## Direct GitHub Install Pattern

If the user gives a GitHub repo directly (for example `owner/repo` or a GitHub URL) and wants it installed, you do **not** need to search first if the request is already specific enough.

Use this flow:

1. Inspect the repo quickly to confirm it contains a root `SKILL.md` or otherwise looks like a valid skill package.
2. Install globally with:

```bash
npx skills add <owner/repo> -g -y
```

Examples:

```bash
npx skills add topviewai/skill -g -y
npx skills add https://github.com/topviewai/skill.git -g -y
```

3. Verify installation with:

```bash
npx skills list -g --json
```

What to expect:
- Global installs typically land under `~/.agents/skills/<skill-name>`
- Some agents also get symlinks or mirrored entries in their own skill directories
- The installed skill name may differ from the repo name, so verify by listing after install

## Post-Install Runtime Setup

Some third-party skills include runnable scripts and extra dependencies (often Python or Node). After installation, inspect the repo for runtime requirements before declaring the setup complete.

Common pattern for Python-based skills:

1. Check for a `scripts/requirements.txt` or similar dependency file
2. If system `pip` is blocked by an externally-managed Python environment (common on macOS/Homebrew), create a per-skill virtualenv instead of forcing a global install
3. Install deps into that virtualenv
4. Run the skill's scripts with the virtualenv interpreter

Example:

```bash
python3 -m venv ~/.agents/skills/<skill-name>/.venv
~/.agents/skills/<skill-name>/.venv/bin/pip install -r ~/.agents/skills/<skill-name>/scripts/requirements.txt
~/.agents/skills/<skill-name>/.venv/bin/python ~/.agents/skills/<skill-name>/scripts/auth.py login
```

Use this when a newly installed skill fails immediately with missing Python modules like `ModuleNotFoundError: requests`.

### Device-login expiration pattern

Some installed skills perform their own OAuth/device login with a helper script such as `auth.py login` and may save a temporary pending-session file.

If the login session sits too long and polling later returns errors like `device code not found`, treat that as an expired or invalid pending session and re-run the login command to issue a fresh authorization link instead of continuing to poll the old one.

Practical rule:

1. Generate a fresh link with the skill's login command
2. Send that new link to the user immediately
3. Only use the skill's `poll`/resume command while that exact pending session is still valid

This is especially useful when the first authorization link expired before the user completed the sign-in step.

## Practical Installation Notes

When the user wants you to install a third-party skill for them (not just find one), use this workflow after discovery:

1. Prefer `npx skills add <owner/repo> -g -y` for a user-level install without prompts.
2. Verify installation with `npx skills list -g --json`.
3. Do **not** assume the skill will appear in Hermes-native `skills_list()` output. The `npx skills` ecosystem installs into `~/.agents/skills/` and may symlink into agent-specific directories; that is a separate layer from Hermes-native `~/.hermes/skills/`.
4. Inspect the installed skill's `README.md` / `SKILL.md` for post-install requirements before declaring success. Many third-party skills need authentication, API keys, or local dependencies after install.
5. If the skill ships Python scripts and `requirements.txt`, be ready to create a per-skill virtualenv instead of installing into the system Python. On macOS/Homebrew Python, plain `pip install -r requirements.txt` may fail with PEP 668 (`externally-managed-environment`). A safe pattern is:

```bash
python3 -m venv <skill_dir>/.venv
<skill_dir>/.venv/bin/pip install -r <skill_dir>/scripts/requirements.txt
```

6. Run the skill's own scripts with that venv interpreter when needed.

## When No Skills Are Found

If no relevant skills exist:

1. Acknowledge that no existing skill was found
2. Offer to help with the task directly using your general capabilities
3. Suggest the user could create their own skill with `npx skills init`

Example:

```
I searched for skills related to "xyz" but didn't find any matches.
I can still help you with this task directly! Would you like me to proceed?

If this is something you do often, you could create your own skill:
npx skills init my-xyz-skill
```
