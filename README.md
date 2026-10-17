# JIT Firewall

A Flask API and browser dashboard for controlling **IPv4 Docker-published host ports** on Ubuntu.

## Features

- Add apps from the dashboard; new ports start **blocked**.
- Edit names and descriptions without changing Python code.
- Allow, block, or temporarily allow access for 1–240 minutes.
- Renew temporary access or cancel its timer with a permanent Allow/Block.
- Remove an app while **leaving its port blocked**.
- Retain app definitions and expiry times across API restarts in SQLite.

The app registry starts empty. Add your apps through the dashboard, or set `JIT_SEED` to a private JSON file before the first startup. Seed records use `id`, `name`, `port`, `proto`, and `description` fields, as shown in [the API documentation](docs/api.md). Seeding registers apps without changing their live firewall state. It only runs when creating the database; subsequent startup does not overwrite saved app definitions.

## Layout

| Path | Purpose |
| --- | --- |
| `app/jit_firewall/` | API, registry storage, firewall adapter and expiry worker |
| `app/wsgi.py` | Gunicorn entry point |
| `app/jit-firewall-api.py` | Development launcher |
| `web/` | Dashboard, app editor, optional nginx Compose service |
| `config/rules.seed.json` | Empty public seed; keep real app inventories outside Git |
| `deploy/` | Generic systemd and sudoers examples |
| `tests/` | API and command-adapter tests with a fake firewall |
| `docs/migration.md` | Generic setup, migration checks, rollback and updates |
| `docs/api.md` | Endpoint contract |

## Installation

Follow [the setup and migration guide](docs/migration.md). All included deployment files use example paths, accounts, and ports; adapt them privately to your environment. No credentials, app inventory, host addresses, or live server configuration are included.

The API runs on the **host** to manage its firewall. An ordinary bridge-network API container would operate in a separate network namespace. Serve the UI from the API at `/`, from the optional nginx service, or from your own reverse proxy. The dashboard's API URL defaults to the page's origin. If your proxy exposes the API under `/api`, enter that base URL and strip the prefix upstream.

A token of at least 32 characters is required; there is no default token. The dashboard keeps it only in tab memory and clears the legacy `jit.token` localStorage entry. Use HTTPS or a trusted private connection. For separate-origin UI hosting, set exact origins in `JIT_CORS_ORIGINS`.

## Firewall semantics

The adapter defaults to `FORWARD` and manages exact `conntrack --ctorigdstport` DROP rules. It can also use `DOCKER-USER` through `JIT_CHAIN`. **Choose the chain that matches your firewall policy.** Changing the setting does not migrate rules from the previous chain.

- This is not a general host firewall manager: it does not edit `INPUT`, SSH rules, UFW, chain policies, or Docker's own chains.
- Each port/protocol matches forwarded traffic globally, rather than one container, address, interface or source network. Register the Docker-published **host** port.
- “Allowed” means this adapter's exact DROP rule is absent; other firewall and routing rules can still deny access.
- IPv6 is **not managed**. Review IPv6 exposure separately.
- Configure all SSH, proxy and management ports in `JIT_PROTECTED_PORTS`. Port 22 and `JIT_PORT` are always protected. The example API/UI ports are also protected by default.
- ID, port and protocol cannot be edited after creation. Remove and re-add to change an endpoint; the old port stays blocked.
- The sudoers template grants broad firewall privileges to its example service account. Keep login disabled and source/service files administrator-owned. A constrained privileged helper would reduce these privileges.
- `netfilter-persistent save` saves the host ruleset, including unrelated rules. Check that this matches your persistence policy.

Temporary expiries are stored before a port is opened, checked every second while the service runs, and reconciled on startup before listening. Failed expiry commands are logged and retried. Each temporary opening first saves a blocked baseline, then removes its DROP without saving that opening.

Temporary access is **not a hard deadline during service downtime**: another action or external ruleset save may persist an opening, and a reboot or firewall reload can expose it until reconciliation. Monitor the service; strict independent expiry and boot-time fail-closed enforcement require additional work. Kernel changes and SQLite transactions cannot be atomic together; failed allows attempt to restore a block and return an error when anything fails.

Legacy `at` jobs are neither imported nor cancelled automatically. Review them during migration.

## Development

```sh
python3 -m venv venv
venv/bin/pip install -r requirements-dev.txt
venv/bin/pytest -q
node --check web/app.js
```

Tests use a fake firewall and do not change host rules. Real deployments need end-to-end checks from another machine. Tested runtime versions are in `app/requirements.lock.txt`; `requirements.txt` documents supported ranges.

Keep real app inventories, environment files, databases, backups, tokens, and host configuration outside this repository. The checked-in deployment templates are generic examples only.
