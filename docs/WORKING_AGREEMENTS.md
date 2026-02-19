# Working Agreements (Human + AI Team)

## Roles
- Human (Katerina): Product Owner / PM, approves PRs, defines policy & priorities
- Tech Lead Agent: plans PRs, maintains architecture consistency
- Backend Agent: bot + db + orchestration
- Analyst Agent: parsing + scoring + market insights
- QA Agent: fixtures + tests + regression guards

## PR rules
- 1 PR = 1 logical change
- PR must include: goal, files, how to test
- Keep diffs small, avoid rewrites

## Token budget rules
- LLM only for tasks that require language reasoning
- No LLM for dedup/policy/limits/state transitions
- Summaries over full context; include only relevant fragments

## Language
- User-facing strings: RU
- Code + identifiers: EN
