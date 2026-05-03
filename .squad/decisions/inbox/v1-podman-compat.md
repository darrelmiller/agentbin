# DevContainer Podman Compatibility

**Status:** Implemented | **Author:** Spec  
**Date:** 2026-08-07

## Decision

The devcontainer configuration now explicitly supports both Docker and Podman (rootless) container runtimes.

## Key Changes

1. **Explicit user mapping** — `remoteUser`, `containerUser`, and `updateRemoteUserUID` set in devcontainer.json so rootless Podman maps host UID correctly
2. **User-level pip installs** — `pip install --user` ensures packages install without root, with `$HOME/.local/bin` on PATH
3. **Idempotent post-create** — TCK clone checks for existing directory; bashrc exports don't duplicate on rebuild
4. **No `--userns=keep-id` in runArgs** — devcontainer CLI v0.50+ auto-detects Podman and injects this; adding it manually would break Docker

## Podman Usage

Users on Podman set:
```bash
export DOCKER_HOST=unix:///run/user/$UID/podman/podman.sock
```

Then `devcontainer up` works identically to Docker. On macOS with `podman machine`, the socket is auto-configured.

## SELinux Note

On Fedora/RHEL with SELinux enforcing, users may need to add to their local devcontainer overrides:
```json
"runArgs": ["--security-opt", "label=disable"]
```

## Team Impact

- No action needed from other agents — changes are purely infrastructure
- All existing Docker workflows remain unchanged
- Podman users can now contribute without permission errors on bind mounts or pip installs
