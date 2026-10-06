# Development

With [devenv](https://devenv.sh) (`devenv shell`, or `direnv allow` if you use
direnv), everything below is already on `PATH`:

| Command | Does |
|---|---|
| `serve` | run the backend on `127.0.0.1:8081` with autoreload |
| `check` | `ruff check` followed by the full test suite |
| `lint` / `fmt` | lint only / autofix and format |
| `version` | print the semver, or bump it: `version patch\|minor\|major` |
| `certs` | generate the self-signed TLS cert |
| `devenv up` | run the backend as a supervised process |
| `devenv test` | what CI would run (`check`) |

The shell pins Python 3.13 (matching the Pi's Debian 13), syncs the venv from
`uv.lock` on entry, and installs git hooks that run `ruff` before each commit.
`SIGNAGE_DB_PATH` points at `signage-dev.db` there, so local runs can never
touch a real `signage.db`.

Without devenv, uv alone is enough:

```sh
uv sync            # creates .venv from uv.lock, including dev dependencies
uv run pytest
```

## Building with Nix

`flake.nix` builds the backend from the same `uv.lock` the Pi installs from, so
the Nix build and `uv sync` resolve to identical dependency versions.

```sh
nix build                     # -> ./result/bin/krautspacetv-backend
nix run . -- --port 8081      # run it; extra args go straight to uvicorn
nix flake check               # builds the package, runs ruff and the test suite
nix develop                   # plain dev shell, if you are not using devenv
```

The built wrapper puts `scrot` on `PATH` (needed by the admin UI's HDMI
preview) and defaults `SIGNAGE_DB_PATH` to `signage.db` in the working
directory, since the package tree itself is read-only in the Nix store.

`nix flake check` deselects `test_ssrf_check_accepts_public_hostname`: it
resolves `example.com` for real, and the Nix sandbox has no network. `check`
and `devenv test` still run it.

The Pi is Debian, not NixOS — it installs via `uv sync` and the systemd units in
`deploy/`. The flake is for building and testing on a workstation.

## Versioning

The project follows [semantic versioning](https://semver.org); the version
lives in `pyproject.toml` and is bumped as part of the change that warrants it
(see `CLAUDE.md` for which kind of change maps to which bump).
