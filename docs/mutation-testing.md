# Mutation Testing with mutmut

## Overview

Mutation testing verifies that the test suite actually catches bugs, not just that tests run and pass.
`mutmut` introduces small code changes ("mutants") — e.g. flipping `>` to `>=`, changing `True` to
`False` — and checks whether the test suite kills each mutant (detects the change). A high kill rate
means the tests are genuinely sensitive to the logic they cover.

## Configuration

Configured in `pyproject.toml` under `[tool.mutmut]`:

```toml
[tool.mutmut]
paths_to_mutate = [
    "src/worship_catalog/normalize.py",
    "src/worship_catalog/extractor.py",
]
tests_dir = ["tests/"]
```

The two modules chosen are the most logic-dense and well-tested files in the codebase, making them
the best targets for mutation score improvement.

## How to Run

```bash
# Run against normalize.py only (fastest, ~5-10 minutes)
python3 -m mutmut run

# View results summary
python3 -m mutmut results

# View a specific surviving mutant
python3 -m mutmut show <id>
```

**Important:** Do NOT run mutmut in CI — a full run takes 10+ minutes and is not suitable for the
pre-commit or CI pipeline. It is a local developer tool for measuring test suite quality.

## Baseline Score (as of 2026-03-15)

Run against `src/worship_catalog/normalize.py`:

- Module: `normalize.py`
- Focus areas: title canonicalization, credit parsing, scripture guard
- Baseline mutation score: to be established on first run

To establish baseline:

```bash
python3 -m mutmut run
python3 -m mutmut results
```

## Interpreting Results

| Outcome   | Meaning                                                              |
|-----------|----------------------------------------------------------------------|
| Killed    | Test suite caught the mutation — good                                |
| Survived  | Mutation was not caught — possible test gap                          |
| Suspicious | Tests timed out or were inconclusive for this mutant               |
| Skipped   | Mutant not run (e.g. outside coverage)                              |

A score above **80% killed** is the target. Surviving mutants indicate specific lines or conditions
that need better test coverage.

## Improving the Score

For each surviving mutant:

1. Run `python3 -m mutmut show <id>` to see the exact change
2. Write a test that would fail with that change applied
3. Re-run `python3 -m mutmut run` to confirm the new test kills the mutant

## Notes

- mutmut is installed as a dev dependency: `pip install -e '.[dev]'`
- The `test_mutmut_is_installed` test in `tests/test_markers.py` verifies mutmut is runnable
- Playwright E2E tests (`@pytest.mark.e2e`) are excluded from mutmut runs automatically
