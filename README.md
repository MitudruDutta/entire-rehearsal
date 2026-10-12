# entire-rehearsal

An [Entire](https://entire.io) CLI plugin that answers two questions about an AI agent you are building:
**which coding-agent session changed it, and does that version still work?**

Entire records the coding-agent session behind every commit as a checkpoint. [Rehearsal](https://rehearsalkit.xyz) tests an AI agent on a sandboxed copy of a real application and decides every outcome from the application's own database. `entire rehearsal` joins the two for the agent in your repository: its instructions (the system prompt) and the code of its tools.

- **history**: every change to the agent, with its checkpoint, the coding agent and model behind it, and, for tool code, the functions [entire-graph](https://docs.entire.io/guides/graph/overview) says changed.
- **status**: is the current version rehearsed? Lists the changes nobody has tested yet.
- **check**: rehearses the current version on a Rehearsal world and records the verdict.
- **report**: each rehearsed change next to its verdict. A regression shows the checkpoint that caused it and what the person asked the coding agent for.
- **gate**: exits 1 unless the current version is rehearsed and ready to pilot, for CI or a pre-push hook.
- Results are git notes on the commits they rehearse, so `sync` shares them with your team.

## Install

Requires the Entire CLI, git and Python 3.10 or newer. entire-graph is optional (`entire plugin install graph`): with it, code changes are named function by function. `check` and `attach` need the Rehearsal client and a sign-in.

```bash
pip install rehearsal-kit && rehearsal login
git clone https://github.com/MitudruDutta/entire-rehearsal
entire plugin install ./entire-rehearsal/entire-rehearsal
```

## Quick start

```bash
entire rehearsal init prompts/support.md --code agent/tools --world wv_...   # once; commit .entire/rehearsal.json
entire rehearsal status          # what changed since the last rehearsal
entire rehearsal check           # rehearse this version (spends model budget; asks first)
entire rehearsal report          # verdicts per change, regressions flagged
entire rehearsal sync            # share results with the team
```

## Commands

| Command | What it does |
|---|---|
| `init INSTRUCTIONS [--code PATH]... [--world WV] [--split dev] [--name N] [--model CHAIN] [--min-success 0.8]` | Writes `.entire/rehearsal.json`, which describes the agent. Every other command reads it, or takes the instructions file as an argument |
| `history [FILE] [--limit 20] [--no-graph] [--json]` | Commits that changed the agent, newest first: which part changed (`instructions`, `code`), the `Entire-Checkpoint`, the coding agent and model, the changed functions, and any recorded verdict |
| `status [FILE] [--no-graph] [--json]` | The current version, the last rehearsed one, and every change in between that nobody has tested |
| `check [FILE] [--world WV] [--split dev] [--repeats 1] [--yes] [--no-wait] [--timeout 120]` | Creates a Rehearsal agent profile from the committed instructions, runs an evaluation, waits, and records the verdict on the commit. **It spends model budget**, so it asks first (`--yes` skips the question). Uncommitted changes are rehearsed but the result is marked dirty |
| `attach RUN_ID [FILE] [--commit SHA]` | Records a finished run you already have against a change (the latest by default). It only reads results |
| `report [FILE] [--limit 50] [--json]` | Each rehearsed change with its verdict, marked better, same or **REGRESSION** against the previous one, with the checkpoint, coding agent and intent behind a regression |
| `gate [FILE] [--min-success 0.8]` | Exit 0 only when the current version has a recorded verdict of ready to pilot; exit 1 otherwise. For CI and pre-push hooks |
| `sync [--remote origin]` | Fetches teammates' results, merges them, and pushes yours (`refs/notes/rehearsal`) |

The verdict uses Rehearsal's readiness bar: **ready to pilot** needs at least 3 finished episodes, 80% or more verified (or your `--min-success`), no rule violations and no false "done" claims.

## Example

`history` and `status` on Rehearsal's own repository, where the agent is the skill Rehearsal gives AI assistants (`rehearsal/assets/skill/SKILL.md`) and the code it drives (`rehearsal/agents`). The checkpoints, coding agents and changed functions are real:

```console
$ entire rehearsal init rehearsal/assets/skill/SKILL.md --code rehearsal/agents
$ entire rehearsal history --limit 3
Changes to the agent (rehearsal/assets/skill/SKILL.md + rehearsal/agents), newest first

d2a2b172  2026-10-11 20:57  [code]  Support the main model providers, not only Nebius
          checkpoint 01M4NS7SH2AGJQTN36VH1RXFP3 · Claude Code (claude-opus-5-5)
          code       top-level code in rehearsal/agents/llm.py changed
5a991961  2026-10-11 00:52  [instructions+code]  Release 0.1.2: browser sign-in for the CLI, cloud database by de
          checkpoint 01M4KM8EECT5ZXY5DWWEQ1CRN2 · Claude Code (claude-opus-5-5)
          code       _client changed (19 dependents)
fc6ddce7  2026-10-10 20:37  [instructions]  Release 0.1.1: agent plugin, rehearsal login, cloud database, re
          checkpoint 01M4K5MZSETW1AW0JCDDSNFK79 · Claude Code (claude-opus-5-5)
```

```console
$ entire rehearsal status
Agent: rehearsal/assets/skill/SKILL.md + rehearsal/agents
Current version: d2a2b172 Support the main model providers, not only Nebius
Last rehearsed:  never

8 changes not rehearsed yet:
  d2a2b172  [code]  Support the main model providers, not only Nebius  · checkpoint 01M4NS7SH2AGJQTN36VH1RXFP3 · Claude Code (claude-opus-5-5)
            code: top-level code in rehearsal/agents/llm.py changed
  5a991961  [instructions+code]  Release 0.1.2: browser sign-in for the CLI, cloud database b  · checkpoint 01M4KM8EECT5ZXY5DWWEQ1CRN2 · Claude Code (claude-opus-5-5)
            code: _client changed (19 dependents)
  ...

Rehearse it with: entire rehearsal check
```

A `report` after three rehearsals, where a change to the tool code made the agent worse (from the test suite, with simulated results):

```console
$ entire rehearsal report
Rehearsal results for prompt.md, newest first

f0414807  ready to pilot ▲ better  90% verified of 6 episodes, 0 rule violations, 0 false 'done', 0 duplicate effects
          [instructions] change 2
          changed in checkpoint 01CPCCCCCC by Claude Code (claude-test)
9981bee0  needs work ▼ REGRESSION  50% verified of 6 episodes, 0 rule violations, 2 false 'done', 0 duplicate effects
          [code] change 1
          changed in checkpoint 01CPBBBBBB by Claude Code (claude-test)
          asked for: "make refunds faster for 01CPBBBBBB"
33a6f07b  ready to pilot  90% verified of 6 episodes, 0 rule violations, 0 false 'done', 0 duplicate effects
          [instructions] change 0
          changed in checkpoint 01CPAAAAAA by Claude Code (claude-test)

Read the session behind a regression with: entire checkpoint explain <checkpoint>
```

## In CI

`gate` reads only the recorded results (git notes), so it needs no Rehearsal account. With the Entire CLI and this plugin installed on the runner:

```bash
git fetch origin refs/notes/rehearsal:refs/notes/rehearsal   # the team's results
entire rehearsal gate                                          # exit 1 blocks the merge
```

To rehearse in CI as well, run `entire rehearsal check --yes` first, with a Rehearsal API key. Entire passes plugins a filtered environment, so the key needs `ENTIRE_PLUGIN_ENV='REHEARSAL_*' entire rehearsal check --yes`. On a laptop, the sign-in saved by `rehearsal login` is used instead.

## Notes

- Commits made without Entire still appear, marked "no checkpoint".
- Results never touch your working tree: they are git notes, in `refs/notes/rehearsal`.
- Without entire-graph, code changes are still listed, just not function by function.

## Development

```bash
python -W error -m unittest discover -s tests -v
```

The tests run every command in throwaway git repositories, with stand-ins for the `entire` CLI and the Rehearsal client, including sharing results through a remote. They need no account and spend nothing.

## License

MIT
