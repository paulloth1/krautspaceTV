{
  description = "krautspaceTV — digital signage for the Krautspace hackerspace";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    # uv2nix builds the dependency set straight out of uv.lock, so a Nix build
    # gets byte-for-byte the versions `uv sync` installs on the Pi. Keeping one
    # lockfile for both is the whole point.
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
    }:
    let
      inherit (nixpkgs) lib;

      # armv7l is the Pi 2 the kiosk actually runs on; the other two are what
      # anyone is realistically developing on.
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "armv7l-linux"
      ];
      forAllSystems = f: lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});

      # pyproject.toml stays the single source of truth for the semver (see CLAUDE.md).
      version = (builtins.fromTOML (builtins.readFile ./pyproject.toml)).project.version;

      workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };

      # Prefer prebuilt wheels over sdists: nothing here needs to be compiled,
      # and sdists would drag in build backends we would then have to patch.
      pyprojectOverlay = workspace.mkPyprojectOverlay { sourcePreference = "wheel"; };

      pythonSetFor =
        pkgs:
        (pkgs.callPackage pyproject-nix.build.packages {
          # Match devenv.nix and the Pi's Debian 13 Python.
          python = pkgs.python313;
        }).overrideScope
          (
            lib.composeManyExtensions [
              pyproject-build-systems.overlays.default
              pyprojectOverlay
            ]
          );

      # Runtime venv: `[project].dependencies` only, no pytest.
      runtimeVenvFor = pkgs: (pythonSetFor pkgs).mkVirtualEnv "krautspacetv-env" workspace.deps.default;

      # Same, plus the `dev` dependency group, for running the test suite.
      testVenvFor = pkgs: (pythonSetFor pkgs).mkVirtualEnv "krautspacetv-test-env" workspace.deps.all;

      packageFor =
        pkgs:
        let
          venv = runtimeVenvFor pkgs;
        in
        pkgs.stdenvNoCC.mkDerivation {
          pname = "krautspacetv";
          inherit version;
          src = self;

          nativeBuildInputs = [ pkgs.makeWrapper ];

          # `backend` is not a Python distribution (pyproject.toml sets
          # `[tool.uv] package = false`), so there is nothing to build — the
          # backend package tree is copied as-is and put on PYTHONPATH. Its
          # templates/ and static/ are found relative to __file__, so they have
          # to travel with it.
          dontBuild = true;

          installPhase = ''
            runHook preInstall

            mkdir -p $out/lib $out/bin
            cp -r backend $out/lib/backend

            # backend/db.py defaults DB_PATH to a path next to the package, which
            # is read-only in the store — fall back to the working directory
            # instead, matching how the systemd units run from ~/signage.
            makeWrapper ${venv}/bin/uvicorn $out/bin/krautspacetv-backend \
              --prefix PYTHONPATH : $out/lib \
              --prefix PATH : ${lib.makeBinPath [ pkgs.scrot ]} \
              --run 'export SIGNAGE_DB_PATH="''${SIGNAGE_DB_PATH:-$PWD/signage.db}"' \
              --add-flags "backend.app:app"

            runHook postInstall
          '';

          meta = {
            description = "Digital signage backend for the Krautspace hackerspace TV";
            homepage = "https://github.com/paulloth1/krautspaceTV";
            mainProgram = "krautspacetv-backend";
            platforms = systems;
          };
        };
    in
    {
      packages = forAllSystems (pkgs: rec {
        default = krautspacetv;
        krautspacetv = packageFor pkgs;
        # The dependency venv on its own, handy for `nix build .#venv` debugging.
        venv = runtimeVenvFor pkgs;
      });

      apps = forAllSystems (pkgs: rec {
        default = backend;
        backend = {
          type = "app";
          program = "${lib.getExe (packageFor pkgs)}";
          meta.description = "Run the signage backend (pass uvicorn flags, e.g. --host/--port)";
        };
      });

      checks = forAllSystems (pkgs: {
        # `nix flake check` builds the package and runs the same suite `check` runs.
        inherit (self.packages.${pkgs.stdenv.hostPlatform.system}) krautspacetv;

        tests = pkgs.stdenvNoCC.mkDerivation {
          name = "krautspacetv-tests";
          src = self;
          nativeBuildInputs = [ (testVenvFor pkgs) ];
          dontBuild = true;
          # Everything else runs happily in the sandbox (tmp_path sqlite files
          # and stubbed HTTP), but this one test resolves example.com for real
          # and the sandbox has no network. It still runs under `check` /
          # `devenv test`, which do.
          checkPhase = ''
            runHook preCheck
            pytest --deselect tests/test_app.py::test_ssrf_check_accepts_public_hostname
            runHook postCheck
          '';
          doCheck = true;
          installPhase = "touch $out";
        };

        lint = pkgs.runCommand "krautspacetv-lint" { nativeBuildInputs = [ pkgs.ruff ]; } ''
          ruff check --no-cache ${self}
          touch $out
        '';
      });

      # `nix develop` for anyone not using devenv. devenv.nix stays the richer
      # environment (scripts, processes, git hooks); this is the plain fallback.
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (testVenvFor pkgs)
            pkgs.ruff
            pkgs.uv
            pkgs.sqlite
          ];
          env = {
            # Point uv at the Nix-built venv rather than letting it manage one.
            UV_NO_SYNC = "1";
            UV_PYTHON_DOWNLOADS = "never";
          };
          shellHook = ''
            echo "krautspaceTV ${version} — nix develop (see devenv.nix for the full dev shell)"
          '';
        };
      });

      formatter = forAllSystems (pkgs: pkgs.nixfmt-tree);
    };
}
