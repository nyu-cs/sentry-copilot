# Contributing

## Development checkout

Use Python 3.12 or newer and work from the repository root:

```bash
python -m venv .venv
# PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
ruff check .
python -m mypy
python tools/validate_repository.py
git diff --check
```

The CLI is available through `python -m sentry_copilot.cli --help` or
`sentry-copilot --help`. Live capture/desktop commands require Windows; ordinary public
tests and the synthetic route demonstration do not require a running game.
See [README](README.md) for the live command and its private-resource requirements.

## Review expectations

- Add or update tests for domain or runtime behavior changes.
- Keep public Python APIs typed and documented; mypy uses strict mode.
- Update the relevant maintained document when a data contract changes.
- Preserve existing user changes and keep unrelated generated/private files out of commits.
- Keep capture, visual observation, domain authority, and presentation responsibilities separate.
- Report unresolved evidence explicitly rather than fabricating a complete result.

Read [Architecture](docs/architecture.md) and [Domain invariants](docs/domain-invariants.md)
before changing state/evidence contracts. The detailed documents linked from
[the documentation index](docs/README.md) describe individual boundaries.

## Scope and resources

The main product is the four-item live encounter assistant. Strategy/player APIs and route
rendering are independent supporting engineering, not additional live-panel features.
Do not silently expand changes into shop recognition, recommendations, deployment, or input
automation.

Do not commit game screenshots, third-party recordings, portraits, icons, or private reference
packs. Public visual tests should use synthetic fixtures or injected observations/adapters.
Game/localization data and technically necessary Japanese recognition literals may remain in
their original languages; explanatory documentation is English-first. Do not rename identity
or resource contracts solely to remove CJK characters.

A declared support target is not evidence of validated real-game support. See
[Validation](docs/validation.md) and [Third-party notices](THIRD_PARTY_NOTICES.md).
