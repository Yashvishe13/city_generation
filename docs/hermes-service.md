# Hermes as a service (grok-4.6 backend)

The vendored agent in `hermes-agent/` runs as a background service rather than an
interactive CLI. Sessions reach it over its JSON-RPC/WebSocket API on
`127.0.0.1:9119`; the CLI is only used for administration.

## Layout of the setup

| Piece | Where |
|---|---|
| Profile | `~/.hermes/profiles/citygen/` |
| Model config | `~/.hermes/profiles/citygen/config.yaml` |
| xAI key | `~/.hermes/profiles/citygen/.env` (`XAI_API_KEY`, mode 600) |
| Service definition | `~/Library/LaunchAgents/ai.hermes.serve-citygen.plist` (template: `tools/ai.hermes.serve-citygen.plist`) |
| Service logs | `~/Library/Logs/hermes-citygen-serve.{out,err}.log` |
| Python env | `hermes-agent/.venv` (`uv sync`, needs uv ≥ 0.12) |

### Why a profile instead of the default install

`~/.hermes/` is an existing working install: model `gpt-5-mini` via `openai-api`, and a
27 KB `.env` of unrelated production credentials (Salesforce, Dynamics/BC, Neo4j,
Vyasa). Repointing it at Grok would have changed that setup. The `citygen` profile has
its own config, its own `.env` containing only `XAI_API_KEY`, and its own service, so
the two do not interact. `serve --isolated` keeps the server bound to this profile
rather than attaching to a machine-level server that would also expose the default one.

## Model

```yaml
model:
  default: grok-4.6
  provider: xai            # API-key provider; xai-oauth is the OAuth variant
  base_url: https://api.x.ai/v1
```

`provider: xai` is the plugin at `hermes-agent/plugins/model-providers/xai/`, which
reads `XAI_API_KEY` and talks to the xAI Responses API.

## Managing the service

```bash
launchctl print    gui/$UID/ai.hermes.serve-citygen      # status, pid, exit code
launchctl kickstart -k gui/$UID/ai.hermes.serve-citygen  # restart
launchctl bootout  gui/$UID/ai.hermes.serve-citygen      # stop and unregister
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/ai.hermes.serve-citygen.plist

curl -s http://127.0.0.1:9119/api/health                 # {"ok":true,...}
```

`RunAtLoad` starts it at login; `KeepAlive` restarts it on a crash or non-zero exit
(verified: `kill -9` was followed by an automatic respawn on a new pid).
`ThrottleInterval` is 10 s so a startup failure cannot spin against the xAI API.

## Administration through the CLI

Only for setup and inspection, not for running work:

```bash
hermes-agent/.venv/bin/hermes -p citygen plugins list        # osm should read "enabled"
hermes-agent/.venv/bin/hermes -p citygen config set model.default grok-4.6
hermes-agent/.venv/bin/hermes -p citygen -z "prompt"         # one-shot, useful for smoke tests
```

## Verified

- `grok-4.6` answers through the profile (`-z` one-shot returned "I am grok-4.6").
- The bundled `osm` plugin is discovered and enabled, and Grok drove it end to end:
  `osm_list_areas` then `osm_tag_stats` for `chicago_loop`, correctly reporting
  `height` at 63/373 (16.9%) and `building:levels` at 213/373 (57.1%).
- Service listens on `127.0.0.1:9119`, answers `/api/health`, and self-restarts.

## Known gaps

- **The browser UI is not built.** `npm ci` refuses the workspace with `EBADENGINE`:
  the repo requires node ≥ 22.22.0 and npm `<11.10.0 || >=11.17.0`, this machine has
  node 22.13.1 / npm 10.9.2. The service therefore runs with `--skip-build` and `GET /`
  returns 404 while `/api/*` works. Upgrading node and running `npm ci && npm run build
  -w web` at `hermes-agent/` would populate `web/dist` and enable the UI.
- **`hermes serve --status` reports "No hermes dashboard processes running"** even while
  the isolated server is up; use `launchctl print` or the health endpoint instead.
- **`auth_required` is false.** Acceptable only because the bind is loopback-only. Any
  non-loopback bind must configure an auth provider first.
- `XAI_API_KEY` now exists in two places: the project `.env` and the profile `.env`.
  The project copy is what a developer edits; the profile copy is what the service
  reads. Keep `.env` out of git.
