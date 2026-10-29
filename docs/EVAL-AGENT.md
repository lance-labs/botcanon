# BotCanon: an independent eval agent (recommended)

This is the tester that pairs with the curator ([docs/CURATOR-AGENT.md](CURATOR-AGENT.md)).

The curator writes the notes and the goldens. If it also grades itself, it tends to test what it already knows how to find, and its goldens drift toward its own phrasing. A score from those goldens measures memory, not retrieval. A separate agent with its own storage keeps a hidden question set that the curator never sees and runs it on a schedule.

Setup:
1. Pick any second agent, or a person. It must not be the agent that writes canon.
2. Copy `tests/fixtures/vault/evals/hidden_set.example.yaml` (format only) into that agent's own storage, outside this repo, and write about 20 questions in its own words. Mix status questions, people questions, rule questions, and must-return-nothing questions.
3. Run it after each batch of changes, or weekly:
   `python3 tools/brain.py --tests /path/outside/repo/hidden_set.yaml verify`
4. The eval agent reports pass/fail and recall@5 to the owner, not the questions. When a question fails, the owner tells the curator what is missing ("flour delivery day"), never the question text.
5. Rotate a few questions each month so the set doesn't become another thing to memorize.

The example file is written against the test fixture, so it runs as-is with `--root tests/fixtures/vault`. Write your real set against your own notes.
