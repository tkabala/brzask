# Agent skills

Procedures for an AI agent connected to brzask over MCP, in the
[Agent Skills](https://agentskills.io) format: one folder per skill, each
with a `SKILL.md`.

| Skill | What it does | Token |
|---|---|---|
| [`weekly-tune-up`](weekly-tune-up/SKILL.md) | Reviews what was shown and opened, checks mutes with a replay, proposes mutes and new sources | propose |
| [`empty-digest`](empty-digest/SKILL.md) | Finds the stage that left today's digest short of 7 | read |
| [`onboarding`](onboarding/SKILL.md) | Builds the interests from a conversation | propose or write |
| [`explain-pick`](explain-pick/SKILL.md) | Explains how an article reached the digest | read |

Install them with Claude Code's plugin manager, or copy the folders into
your agent's skills directory. See [Agents](../docs/agents.md#skills).
