# Setup and migration

All paths, accounts, and ports below are **generic examples**, not a live deployment configuration. Adapt them privately. The public app registry is empty; real inventories belong outside Git.

## Back up and inspect an existing installation

Keep an administrative session open. Back up application files, the existing service unit, environment files, sudo policies, app definitions, and IPv4/IPv6 rules to a private location. Record the current commit and take a VM snapshot if available. Never commit these backups.

Inspect the existing bind address, API/UI ports, SSH port, reverse proxy routing, service account, firewall chain, and persistence policy. Configure `JIT_PROTECTED_PORTS` to protect every management port. Choose the existing chain deliberately: changing `JIT_CHAIN` does not move or remove old rules.

If migrating from an implementation that uses `at`, inspect pending jobs under each relevant owner with `atq` and `at -c JOB_ID`. Only cancel confirmed application reblock jobs, after blocking the related app or preserving its desired deadline. Do not cancel unrelated jobs. Legacy jobs left queued can override a later permanent allow.

## Install in a new directory

For a new example installation, use `/srv/jit-firewall` and the system account `jit-firewall`. For an existing installation, stage the checkout separately and adjust the unit to your chosen directory. Avoid overwriting the old installation before verification.

```sh
sudo apt-get update
sudo apt-get install -y git python3-venv sudo iptables iptables-persistent
sudo git clone https://github.com/Darthcedeus/jit.git /srv/jit-firewall
cd /srv/jit-firewall
sudo python3 -m venv venv
sudo venv/bin/pip install -r app/requirements.lock.txt
```

The API must run in the host network namespace. Keep the checkout and virtual environment administrator-owned; give the service account write access only to its state directory.

## Configure privately

The example unit uses the system account `jit-firewall`, `/etc/jit-firewall.env`, and `/var/lib/jit-firewall`. Create the account if needed:

```sh
sudo useradd --system --home-dir /var/lib/jit-firewall --shell /usr/sbin/nologin jit-firewall
sudo install -m 600 .env.example /etc/jit-firewall.env
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
sudoedit /etc/jit-firewall.env
```

Skip account creation if it already exists. Put the generated token in the private environment file. Set `JIT_HOST` and `JIT_PORT` for your listener; the example uses loopback and a generic API port. Add actual management ports to `JIT_PROTECTED_PORTS`. Configure exact `JIT_CORS_ORIGINS` if UI and API use different origins. Preserve your existing reverse proxy routing, including any stripped API prefix.

For an existing app inventory, write a private seed file outside the checkout with the record format documented in `docs/api.md`, and set `JIT_SEED` to its path **before first startup**. Make it readable by the service account. Seeding does not change live rules and does not rerun once the database exists. Without a seed, add apps through the dashboard; creating an app blocks its port immediately.

Review `deploy/sudoers.example`. It grants broad firewall administration rights to the example service account; use an existing suitable policy or adapt the template deliberately. If installing it:

```sh
sudo install -m 440 deploy/sudoers.example /etc/sudoers.d/jit-firewall
sudo visudo -cf /etc/sudoers.d/jit-firewall
sudo -u jit-firewall sudo -n /usr/sbin/iptables -S FORWARD
```

For a different chain, adapt the inspection command. The application does not flush chains or change default policies.

## Start and verify

After stopping any previous API process and recording how to restore it:

```sh
sudo install -m 644 deploy/jit-firewall.service /etc/systemd/system/jit-firewall.service
sudo systemctl daemon-reload
sudo systemctl enable --now jit-firewall
sudo systemctl status jit-firewall --no-pager
sudo journalctl -u jit-firewall -n 50 --no-pager
```

The unit creates the state directory with restricted permissions. Virtual-environment launch scripts contain absolute paths; rebuild the environment if you move its installation directory.

Check `/health` at your configured listener. It confirms HTTP liveness only. Connect the dashboard with the token to verify authenticated firewall inspection. The API can serve the UI directly, or `web/docker-compose.yml` provides an optional standalone nginx example. A separate UI needs a reachable API URL and an allowed CORS origin. Re-enter the token after page reloads.

From another machine, verify one blocked app and one allowed app. Use a disposable, non-management published port to test creation, temporary allow, expiry, editing, and removal. New apps must start blocked; removed apps must remain blocked. Test an API restart during a temporary allow and inspect the logs and actual rules. Review IPv6 separately, and read the downtime/persistence limitations in the README.

## Rollback

Stop the new service. Preserve its database and checkout for diagnosis, then restore the previous application, service, environment, and sudo policy from private backups. Reload systemd and restart the previous service. Restore previous UI routing if changed. Keep the administrative session open until connectivity is verified.

Do not blindly restore a full saved ruleset while Docker or other networking services are running; runtime rules may have changed. Review newly added application DROP rules separately. Rolling back the application does not automatically remove them or recreate old scheduled jobs.

## Future updates

Stop the service during a maintenance window, back up its state privately, record the current commit, then run `git pull --ff-only`, install `app/requirements.lock.txt`, and restart. Keep the database, real seed, and environment file outside the checkout. No unattended deployment is configured.
