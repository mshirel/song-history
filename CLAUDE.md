# Claude Code — Project Instructions

## TDD is Non-Negotiable

**All code changes must be test-driven. No exceptions.**

### The Rule

1. **Write tests first.** Before writing any implementation code, write failing tests that define the expected behavior.
2. **Confirm tests fail.** Run `python3 -m pytest <new_test_file>` and verify the new tests fail for the right reason (not import errors — the behavior is missing).
3. **Write the minimum implementation** to make the tests pass.
4. **Confirm all tests pass.** Run the full suite: `python3 -m pytest`. No regressions allowed.
5. **Only then commit.**

### Issues Must Have Tests

Every GitHub issue created must include a **"Tests to write first"** section with concrete, runnable test code. Issues without test cases are incomplete and should not be worked.

When creating issues:
- Include the test class name, method names, and assertions
- Tests must be specific enough to be copied directly into the test file
- Cover the happy path, the failure path, and edge cases

### What Counts as a Test

- Python unit tests in `tests/` using pytest
- Integration tests decorated with `@pytest.mark.integration`
- Shell tests for bash scripts (using bats-core or inline assertions)
- CI pipeline assertions (workflow steps that verify behavior)

CI config changes and documentation-only changes are exempt, but any change touching Python source or shell scripts requires tests.

---

## Development Workflow

```
1. Read the issue — understand the test cases defined there
2. Write tests → run → confirm they FAIL
3. Write implementation → run → confirm they PASS
4. Run full suite: python3 -m pytest
5. Run linter: python3 -m ruff check src/
6. Run type check: python3 -m mypy src/
7. Commit and push
8. Confirm CI passes before closing the issue
```

---

## Project Stack

- **Language:** Python 3.12
- **CLI:** Click
- **Web:** FastAPI + HTMX + Jinja2
- **DB:** SQLite via custom `Database` class (`src/worship_catalog/db.py`)
- **Testing:** pytest with coverage (`python3 -m pytest`)
- **Linting:** ruff + mypy (strict)
- **Security:** bandit + pip-audit + gitleaks (all in CI)
- **Container:** Docker + Docker Compose

---

## Code Quality Rules

- `ruff` and `mypy --strict` must pass with zero errors before any commit
- No bare `except Exception` that swallows errors silently — log the reason
- No hardcoded magic numbers — use named constants at module level
- No `TODO` comments in production code — file an issue instead
- No module-wide `# type: ignore` or `ignore_errors = true` additions without prior discussion

---

## Security Rules

- Never interpolate user-controlled values into shell commands or SQL strings
- Always use parameterized queries — never f-strings with user data in SQL
- Never log raw query parameters — sanitize before writing to logs
- Never bake secrets into Docker images or commit them to git
- All new POST endpoints must include CSRF protection
- File inputs (PPTX) must be validated for size before loading

---

## Test File Conventions

| What you're testing | Test file |
|---|---|
| CLI commands | `tests/test_cli.py` |
| Database layer | `tests/test_db_integration.py` |
| Web routes | `tests/test_web.py` |
| Extraction logic | `tests/test_extractor_unit.py` |
| OCR / Vision API | `tests/test_ocr.py` |
| Normalization / credits | `tests/test_credits_parsing.py` |
| PPTX parsing | `tests/test_pptx_reader_unit.py` |
| Log config | `tests/test_log_config.py` |
| Security-specific | `tests/test_web_security.py` |
| Bash scripts | `tests/test_scripts.bats` (bats-core) |

Run a specific file: `python3 -m pytest tests/test_web.py -v`
Run with coverage: `python3 -m pytest --cov=worship_catalog`
Run only fast tests: `python3 -m pytest -m "not integration"`

---

## GitHub Issue Labels

Every issue should carry at least one **topic label** and, where applicable, one or more **qualifier labels**.

### Topic labels (what area the issue is in)

| Label | Use when |
|---|---|
| `bug` | Something that was working is broken |
| `regression` | Behavior that previously worked is now broken (subset of bug) |
| `enhancement` | New feature or improvement |
| `security` | Security vulnerability or hardening |
| `performance` | Speed, memory, or resource usage |
| `architecture` | System design, abstractions, coupling |
| `code-quality` | Readability, patterns, maintainability |
| `devops` | CI/CD, Docker, deployment, observability |
| `devsecops` | Supply chain, scanning, dependency management |
| `infrastructure` | Infrastructure and deployment config |
| `web-ui` | Web routes, templates, HTMX behaviour, forms |
| `cli-contract` | CLI command interface, flags, or output format |
| `ux` | User experience — flows, copy, layout, usability |
| `accessibility` | ARIA, keyboard navigation, screen reader, contrast |
| `documentation` | Docs-only changes |

### Qualifier labels (lifecycle / process)

| Label | Use when |
|---|---|
| `qa-found` | Issue was identified during QA or automated testing |
| `uat` | Issue requires user acceptance testing before closing |
| `deferred` | Intentionally out of scope — do not pick up until re-prioritized |
| `wontfix` | Will not be worked, ever |
| `good first issue` | Low complexity, safe starting point for new contributors |
| `help wanted` | Needs extra attention or outside input |

### Filtering deferred issues

```bash
gh issue list --state open --label "!deferred"
```
