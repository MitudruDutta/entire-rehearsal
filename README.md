# entire-rehearsal

An [Entire](https://entire.io) CLI plugin that answers two questions about an AI agent you are building:
**which coding-agent session changed its instructions, and does that version still work?**

Entire records the agent session behind every commit as a checkpoint. [Rehearsal](https://rehearsalkit.xyz) tests an AI agent on a sandboxed copy of a real application and decides every outcome from the application's own database. `entire rehearsal` joins the two for one file: your agent's instructions (its system prompt).

```console
$ entire rehearsal history prompts/support-agent.md
$ entire rehearsal check   prompts/support-agent.md --world wv_...   # rehearse the current version
$ entire rehearsal report  prompts/support-agent.md                  # each change next to its result
```

When a change makes the agent worse, the report points at the change and the checkpoint behind it. `entire checkpoint explain <checkpoint>` then shows the prompts and reasoning that produced it.

## Install

Requires the Entire CLI, git and Python 3.10 or newer. `check` and `attach` also need the Rehearsal client and a sign-in:

```bash
pip install rehearsal-kit && rehearsal login
git clone https://github.com/MitudruDutta/entire-rehearsal
entire plugin install ./entire-rehearsal/entire-rehearsal
entire rehearsal --help
```

## Commands

| Command | What it does |
|---|---|
| `entire rehearsal history FILE` | Commits that changed the file, newest first, each with its `Entire-Checkpoint` and the coding agent and model behind it |
| `entire rehearsal check FILE --world WV_ID` | Creates a Rehearsal agent profile from the committed file, runs an evaluation on that world (`--split dev` by default, `--repeats 1`), waits, and records the verdict against the commit. **It spends model budget**, so it asks first; `--yes` skips the question, `--no-wait` records the run without waiting |
| `entire rehearsal attach RUN_ID FILE [--commit SHA]` | Records a run you already have against a change (the latest by default). It only reads results |
| `entire rehearsal report FILE` | Each rehearsed change with its verdict, marked better, same or **REGRESSION** against the previous one, and the checkpoint that made it |

The verdict uses the same bar as Rehearsal's readiness board: **ready to pilot** needs at least 3 finished episodes, 80% or more verified, no rule violations and no false "done" claims; anything lower **needs work**.

Results are kept in the plugin's data directory (`ENTIRE_PLUGIN_DATA_DIR`), one file per repository, and nothing is written to the repository itself.

## Example

`history` on Rehearsal's own repository, for the instructions Rehearsal gives AI assistants (`rehearsal/assets/skill/SKILL.md`):

```console
$ entire rehearsal history rehearsal/assets/skill/SKILL.md --limit 4
Changes to rehearsal/assets/skill/SKILL.md, newest first

5a991961  2026-10-11 00:52  Release 0.1.2: browser sign-in for the CLI, cloud database by default,
          checkpoint 01M4KM8EECT5ZXY5DWWEQ1CRN2 · Claude Code (claude-opus-5-5)
fc6ddce7  2026-10-10 20:37  Release 0.1.1: agent plugin, rehearsal login, cloud database, release
          checkpoint 01M4K5MZSETW1AW0JCDDSNFK79 · Claude Code (claude-opus-5-5)
cba698b6  2026-10-10 18:55  Fix billing and SDK reliability; automate PyPI releases
          checkpoint — · no checkpoint
65aa79a6  2026-10-10 15:20  Repeat the customer's request after the first change, by default
          checkpoint 01M4JKGANJPG1QNR6H54YFHDNM · Claude Code (claude-opus-5-5)
```

A `report` after two rehearsals, where the latest change made the agent worse (from the test suite):

```console
$ entire rehearsal report prompt.md
Rehearsal results for prompt.md, newest first

c028311d  needs work ▼ REGRESSION  50% verified of 6 episodes, 0 rule violations, 2 false 'done', 0 duplicate effects
          change 2
          changed without an Entire checkpoint
e72edd0d  ready to pilot  90% verified of 6 episodes, 0 rule violations, 0 false 'done', 0 duplicate effects
          change 1
          changed in checkpoint 01CPBBBBBB by Claude Code (claude-test)

Read the session behind a regression with: entire checkpoint explain <checkpoint>
```

## Notes

- Entire passes plugins a filtered environment. The Rehearsal client reads the sign-in saved by `rehearsal login`; to use `REHEARSAL_API_KEY` and `REHEARSAL_URL` instead (in CI, for example), run with `ENTIRE_PLUGIN_ENV='REHEARSAL_*'`.
- `check` rehearses the file as committed. With uncommitted edits it warns and marks the result as dirty.
- Commits made without Entire still appear in `history`, without a checkpoint.

## Development

```bash
python -W error -m unittest discover -s tests -v
```

The tests build a throwaway git repository and use stand-ins for the `entire` CLI and the Rehearsal client, so they need no account and spend nothing.

## License

MIT
