# waicomputer-brain — OpenClaw skill

Gives an [OpenClaw](https://openclaw.ai) agent a second brain by connecting
[WaiComputer](https://wai.computer) over MCP, plus guidance on when to recall and
when to remember.

> Status: **draft** maintained in the WaiComputer repo. The integration itself
> (the MCP server) is live and works today via the CLI in
> [`SKILL.md`](./SKILL.md); this directory packages that as a reusable skill /
> ClawHub entry. Final ClawHub packaging may need a tweak to match the current
> submission format.

## Install

The integration is just an MCP server, so you can use it without the skill:

```bash
openclaw mcp add waicomputer --url https://wai.computer/mcp \
  --transport streamable-http --auth oauth
openclaw mcp login waicomputer
```

Or, once published, install the skill (bundles the config + usage guidance):

```bash
openclaw skills add waicomputer-brain
```

See [`SKILL.md`](./SKILL.md) for the tool list, the write-access (memory bank)
token form, and when the agent should recall vs. remember.
