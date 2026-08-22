# CLAUDE.md

Digital signage for the Krautspace hackerspace: a FastAPI backend that rotates
slides, plus a Chromium kiosk on a Raspberry Pi 2 that displays them. See
`README.md` for the architecture, the slide types, and the Pi deployment.

## Versioning

**This project uses [semantic versioning](https://semver.org). Bump the version
as part of the change that warrants it — do not leave it for later.**

The single source of truth is `version` in `pyproject.toml`. `uv.lock` records
the same value, so both files change together.

Which bump applies:

| Bump | For |
|---|---|
| **major** | A change an operator must react to: a removed or renamed slide type or config field, a stored-config format that old data no longer satisfies, a moved API path or systemd unit, a changed deployment step. |
| **minor** | New capability that leaves everything existing working: a new slide type, a new config field, a new endpoint or overlay. |
| **patch** | Bug fixes, `/proxy` rewrite tweaks, dependency bumps, tests, docs, refactors with no outward change. |

Bump it with the `version` script from the devenv shell, which edits
`pyproject.toml` and re-locks in one step:

```sh
version patch     # or: minor, major
version           # print the current version
```

If you are not in the devenv shell, edit `pyproject.toml` by hand and then run
`uv lock` — otherwise `uv run --frozen` and `uv sync --frozen` fail against a
stale lock.

When a single change touches several categories, take the highest one. A commit
that only reformats or only edits `README.md` needs no bump.

## Dependencies

Managed by uv. `pyproject.toml` holds the declarations, `uv.lock` the resolved
pins, and both are committed.

- Runtime dependencies go in `[project].dependencies`, pinned exactly (`==`) —
  the Pi is slow and fragile, and a surprise upgrade there is expensive.
- Test-only dependencies go in `[dependency-groups].dev`.
- After editing either, run `uv lock` and commit the lockfile.
- `ruff` is deliberately *not* a dev dependency: its PyPI wheel is a generic
  dynamically-linked binary that does not run on NixOS, so devenv supplies it
  from nixpkgs instead.

## Working in this repo

`devenv shell` puts these on `PATH` (`serve`, `check`, `lint`, `fmt`,
`version`, `certs`); `devenv.nix` defines them.

- `check` — `ruff check` then `pytest`. Run it before calling a change done.
- `serve` — the backend on `127.0.0.1:8081` with autoreload, against
  `signage-dev.db` rather than the deployed `signage.db`.
- Git hooks run `ruff` on commit.

Without devenv: `uv sync` then `uv run pytest`.

## Things to keep in mind

- Import order in `backend/slides/__init__.py` is deliberate, not alphabetical —
  it sets the order of the admin UI's slide-type picker, so isort is disabled
  for that file.
- The backend runs as four uvicorn processes on the Pi; only the one with
  `SIGNAGE_ROTATION_OWNER=1` drives rotation, and the others forward to it. A
  change to the current-slide state has to work through both paths.
- The Pi 2 has a weak CPU and 900MB of RAM. Anything that adds per-poll work to
  `/display` or `/proxy` is a real cost there.
- No secrets in git. The SQLite database (`signage.db`) and the TLS cert
  (`certs/`) are gitignored and generated per host.
