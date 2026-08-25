{ pkgs, config, ... }:

let
  # Anchor everything to the repo root so the scripts behave the same no matter
  # which subdirectory you launched the shell from.
  root = config.devenv.root;
in
{
  # https://devenv.sh/languages/
  languages.python = {
    enable = true;
    # Matches the Pi's Raspberry Pi OS (Debian 13 "trixie") system Python, so a
    # dependency that resolves here also resolves on the target.
    package = pkgs.python313;

    uv = {
      enable = true;
      # Creates/refreshes .devenv/state/venv from uv.lock on every shell entry, so the
      # environment can never silently drift from the lockfile.
      sync.enable = true;
    };
  };

  # https://devenv.sh/packages/
  packages = with pkgs; [
    git
    # ruff comes from nixpkgs, not the dev dependency group: the PyPI wheel is a
    # generic dynamically-linked ELF that will not run on NixOS.
    ruff
    sqlite # inspect signage.db by hand
    openssl # generate the self-signed kiosk TLS cert
    curl # poke the API endpoints
  ];

  env = {
    # Keep the dev database out of the deployed filename, so a local run can never
    # be confused with (or clobber) the Pi's signage.db.
    SIGNAGE_DB_PATH = "${root}/signage-dev.db";
    # Run the rotation loop locally. In production only the kiosk-internal instance
    # sets this, but a lone dev process should behave like the owner.
    SIGNAGE_ROTATION_OWNER = "1";
  };

  # https://devenv.sh/scripts/
  scripts = {
    serve.exec = ''
      cd "${root}"
      exec uv run --frozen uvicorn backend.app:app --reload --host 127.0.0.1 --port 8081 "$@"
    '';
    serve.description = "Run the backend with autoreload on 127.0.0.1:8081";

    # Not named `test`: that is a bash builtin and would never reach PATH.
    check.exec = ''
      set -e
      cd "${root}"
      ruff check .
      exec uv run --frozen pytest "$@"
    '';
    check.description = "Lint with ruff, then run the test suite";

    lint.exec = ''
      cd "${root}"
      exec ruff check "$@" .
    '';
    lint.description = "Lint with ruff";

    fmt.exec = ''
      set -e
      cd "${root}"
      ruff check --fix .
      exec ruff format .
    '';
    fmt.description = "Autofix lint findings, then format with ruff";

    version.exec = ''
      set -e
      file="${root}/pyproject.toml"
      current=$(sed -n 's/^version = "\(.*\)"$/\1/p' "$file" | head -1)
      if [ $# -eq 0 ]; then
        echo "$current"
        exit 0
      fi
      major=''${current%%.*}
      rest=''${current#*.}
      minor=''${rest%%.*}
      patch=''${rest##*.}
      case "$1" in
        major) major=$((major + 1)); minor=0; patch=0 ;;
        minor) minor=$((minor + 1)); patch=0 ;;
        patch) patch=$((patch + 1)) ;;
        *) echo "usage: version [major|minor|patch]" >&2; exit 2 ;;
      esac
      new="$major.$minor.$patch"
      sed -i "0,/^version = \"$current\"$/s//version = \"$new\"/" "$file"
      # uv.lock pins the project's own version too, so `uv run --frozen` starts
      # failing the moment pyproject.toml moves ahead of it.
      uv lock --quiet
      echo "$new"
    '';
    version.description = "Print the semver from pyproject.toml, or bump it: version [major|minor|patch]";

    certs.exec = ''
      set -e
      mkdir -p "${root}/certs"
      openssl req -x509 -newkey rsa:2048 \
        -keyout "${root}/certs/key.pem" -out "${root}/certs/cert.pem" \
        -days 3650 -nodes -subj '/CN=krautspaceTV' \
        -addext 'subjectAltName=DNS:krautspaceTV,DNS:krautspaceTV.local,DNS:localhost,IP:127.0.0.1'
    '';
    certs.description = "Generate the self-signed TLS cert the HTTPS services use";
  };

  # https://devenv.sh/processes/ — `devenv up` mirrors the Pi's kiosk-internal
  # instance (the only one that owns rotation). The three LAN-facing forwarding
  # services exist only to share one rotation state across ports, which is
  # pointless with a single local process.
  processes.backend.exec = "serve";

  # https://devenv.sh/git-hooks/
  git-hooks.hooks = {
    ruff.enable = true;
    check-toml.enable = true;
    check-merge-conflicts.enable = true;
  };

  # https://devenv.sh/tests/
  enterTest = ''
    check
  '';

  enterShell = ''
    # devenv's uv integration syncs .devenv/state/venv but leaves it off PATH;
    # putting it on makes bare `pytest` / `uvicorn` work without a `uv run` prefix.
    export PATH="$UV_PROJECT_ENVIRONMENT/bin:$PATH"

    echo "krautspaceTV $(version) — dev shell"
    echo "  serve    run the backend on 127.0.0.1:8081 (autoreload)"
    echo "  check    ruff check + pytest (bare \`pytest -k ...\` to narrow)"
    echo "  lint     ruff check           fmt  ruff autofix + format"
    echo "  version  show/bump the semver in pyproject.toml"
    echo "  certs    generate the self-signed TLS cert"
  '';
}
