# BotCanon: Extending the boundary

The core is one person's fact store: their agents read from it and propose into it. To search other content with the same engine, such as a novel or a codebase's docs, make it a separate store with its own index and its own `retrieval_tests.yaml`. Never mix the two. Facts about your life and lines of fiction have different authority rules. Mixed goldens hide failures in both, and one store's freshness alarms would block the other's commits.

```sh
# a store is any folder; --dirs names the content folders to index
python3 tools/brain.py --root examples/novel --dirs chapters ingest
python3 tools/brain.py --root examples/novel --dirs chapters search "where did the keeper go"
python3 tools/brain.py --root examples/novel --dirs chapters verify
# or: BRAIN_VAULT=/path/to/store BRAIN_DIRS=chapters,notes python3 tools/brain.py verify
```

Each store keeps its own `.index/` and reads goldens from `<root>/retrieval_tests.yaml`, else `<root>/evals/retrieval_tests.yaml` (or pass `--tests`). `examples/novel/` is a two-chapter worked example whose goldens include a check that nothing from the fact store leaks in. For a codebase, point `--dirs` at its Markdown docs, such as `docs,adr`. The engine indexes `.md` only.

This works with any agent that can run a shell command. One worked example is Grok Bot: one bot curates the fact store, another owns the novel store, and each runs `flush` on its own store only. Nothing here depends on Grok Bot.
