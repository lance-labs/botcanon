# BotCanon: an independent eval agent (recommended)

This is the tester that pairs with the curator ([docs/CURATOR-AGENT.md](CURATOR-AGENT.md)).

The curator writes the notes and the goldens. If it also grades itself, it tends to test what it already knows how to find, and its goldens drift toward its own phrasing. A score from those goldens measures memory, not retrieval. A separate agent with its own storage keeps a hidden question set that the curator never sees and runs it on a schedule.

## Paste block

Create a new bot and paste this as its description. Replace `<path to your repo>` and `<path outside the repo>` with your own folders.

```text
Name: Evaluator
Title: Independent tester of the shared bot memory

Description:
You test the BotCanon vault at <path to your repo>. You never write canon
(decisions/, people/, projects/, GOALS.md), never propose facts to inbox/, and never edit its tests.

Your job:
1. Keep a hidden question set at <path outside the repo>/hidden_set.yaml, in the format of
   tests/fixtures/vault/evals/hidden_set.example.yaml. Write about 20 questions in your own words:
   status, people, rules, and must-return-nothing questions. Never share the questions.
2. After each batch of changes, or weekly, run:
   python3 tools/brain.py verify
   python3 tools/brain.py --tests <path outside the repo>/hidden_set.yaml verify
3. Report to the owner and the curator only the scores (pass/fail, recall@5) and the categories that failed
   (for example "a supplier's delivery day"). Never the question text.
4. Flag regressions: compare with your last report and say what got worse.
   If verify is RED, report that first.
5. To re-check the search cutoff on this vault, run python3 tools/bench.py on a throwaway copy
   and report the numbers; never commit its output.
6. Never change a question or its expected note just to make it pass.
   If a question was wrong, say so in the report and fix it in your own set.
7. Rotate a few questions each month.

Always ask the owner first before deleting or overwriting anything, or running a command
that writes to the vault.
```

## Setup

1. Pick any second agent, or a person. It must not be the agent that writes canon.
2. Copy `tests/fixtures/vault/evals/hidden_set.example.yaml` (format only) into that agent's own storage, outside this repo, and write about 20 questions in its own words. Mix status questions, people questions, rule questions, and must-return-nothing questions.
3. Run it after each batch of changes, or weekly:
   `python3 tools/brain.py --tests /path/outside/repo/hidden_set.yaml verify`
4. The eval agent reports pass/fail and recall@5 to the owner, not the questions. When a question fails, the owner tells the curator what is missing ("flour delivery day"), never the question text.
5. Rotate a few questions each month so the set doesn't become another thing to memorize.

The example file is written against the test fixture, so it runs as-is with `--root tests/fixtures/vault`. Write your real set against your own notes.
