"""Authenticated app registry and Docker published-port controls."""
import hmac
import logging
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .firewall import Firewall
from .store import Store

ROOT = Path(__file__).resolve().parents[2]
LOG = logging.getLogger(__name__)


def create_app(config=None, firewall=None):
    app = Flask(__name__, static_folder=str(ROOT / 'web'), static_url_path='/web')
    app.config.update(
        API_TOKEN=os.getenv('JIT_API_TOKEN', ''),
        DATABASE=os.getenv('JIT_DATABASE', '/var/lib/jit-firewall/rules.sqlite3'),
        SEED=os.getenv('JIT_SEED', str(ROOT / 'config/rules.seed.json')),
        PROTECTED_PORTS=os.getenv('JIT_PROTECTED_PORTS', '22,8765,9080'),
        CORS_ORIGINS=os.getenv('JIT_CORS_ORIGINS', ''),
        MAX_CONTENT_LENGTH=16384,
    )
    app.config.update(config or {})
    token = app.config['API_TOKEN']
    if len(token) < 32:
        raise ValueError('Set JIT_API_TOKEN to at least 32 characters')
    protected = {int(p.strip()) for p in app.config['PROTECTED_PORTS'].split(',') if p.strip()}
    protected |= {22, int(os.getenv('JIT_PORT', '8765'))}
    store = Store(app.config['DATABASE'], app.config['SEED'])
    fw = firewall or Firewall(os.getenv('JIT_CHAIN', 'FORWARD'))
    app.extensions.update(store=store, firewall=fw)

    @app.before_request
    def auth():
        if request.method == 'OPTIONS':
            return '', 204
        if request.path in ('/', '/health') or request.path.startswith('/web/'):
            return None
        supplied = request.headers.get('Authorization', '')
        if not hmac.compare_digest(supplied.encode(), f'Bearer {token}'.encode()):
            return jsonify(ok=False, error='Unauthorized'), 401

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        origins = {o.strip() for o in app.config['CORS_ORIGINS'].split(',') if o.strip()}
        if request.headers.get('Origin') in origins:
            response.headers['Access-Control-Allow-Origin'] = request.headers['Origin']
            response.headers['Vary'] = 'Origin'
            response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PATCH, DELETE, OPTIONS'
        return response

    @app.errorhandler(Exception)
    def error(exc):
        if isinstance(exc, HTTPException):
            return jsonify(ok=False, error=exc.description), exc.code
        if isinstance(exc, ValueError):
            return jsonify(ok=False, error=str(exc)), 400
        if isinstance(exc, sqlite3.IntegrityError):
            return jsonify(ok=False, error='App ID or port/protocol already registered'), 409
        LOG.exception('Request failed')
        return jsonify(ok=False, error='Operation failed; check service logs before retrying'), 503

    def body():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError('Expected a JSON object')
        return data

    def validated(data, editing=False):
        fields = {'name', 'description'} if editing else {'id', 'name', 'port', 'proto', 'description'}
        if set(data) - fields:
            raise ValueError('Unknown fields; port, protocol and ID cannot be changed after creation')
        result = {}
        for key, limit in [('name', 100), ('description', 500)]:
            value = data.get(key, '' if not editing else None)
            if value is None and editing:
                continue
            if not isinstance(value, str) or len(value) > limit or (key == 'name' and not value.strip()):
                raise ValueError(f'{key} must be text (maximum {limit} characters); name is required')
            result[key] = value.strip()
        if not editing:
            rid = data.get('id', '')
            if not isinstance(rid, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', rid):
                raise ValueError('ID must contain 1–64 letters, digits, underscores or hyphens')
            port = data.get('port')
            if type(port) is not int or not 1 <= port <= 65535 or port in protected:
                raise ValueError('Port must be an integer from 1–65535 and cannot be a protected management port')
            proto = data.get('proto', 'tcp')
            if proto not in ('tcp', 'udp'):
                raise ValueError('Protocol must be tcp or udp')
            result.update(id=rid, port=port, proto=proto)
        return result

    def get(db, rid):
        from werkzeug.exceptions import NotFound
        rule = db.execute('SELECT * FROM rules WHERE id=?', (rid,)).fetchone()
        if rule is None:
            raise NotFound('Unknown app')
        return dict(rule)

    def serialize(rule):
        blocked = fw.blocked(rule)
        return dict(rule, blocked=blocked, allowed=not blocked)

    def expire():
        with store.transaction() as db:
            for row in db.execute('SELECT * FROM rules WHERE expires_at IS NOT NULL AND expires_at<=?', (time.time(),)).fetchall():
                fw.block(dict(row))
                db.execute('UPDATE rules SET expires_at=NULL WHERE id=?', (row['id'],))
    app.extensions['expire'] = expire

    @app.get('/')
    def index():
        return app.send_static_file('index.html')

    @app.get('/health')
    def health():
        return jsonify(ok=True, service='jit-firewall-api')

    @app.get('/rules')
    def rules():
        expire()
        with store.transaction() as db:
            return jsonify(ok=True, rules=[serialize(dict(row)) for row in db.execute('SELECT * FROM rules ORDER BY rowid')])

    @app.get('/rules/<rid>')
    def read(rid):
        expire()
        with store.transaction() as db:
            return jsonify(ok=True, rule=serialize(get(db, rid)))

    @app.post('/rules')
    def create():
        rule = validated(body())
        with store.transaction() as db:
            db.execute('INSERT INTO rules(id,name,port,proto,description) VALUES(:id,:name,:port,:proto,:description)', rule)
            fw.block(rule)  # New apps always start blocked.
            return jsonify(ok=True, rule=serialize(get(db, rule['id']))), 201

    @app.patch('/rules/<rid>')
    def edit(rid):
        changes = validated(body(), editing=True)
        with store.transaction() as db:
            rule = get(db, rid)
            rule.update(changes)
            db.execute('UPDATE rules SET name=?,description=? WHERE id=?', (rule['name'], rule['description'], rid))
            return jsonify(ok=True, rule=serialize(get(db, rid)))

    @app.delete('/rules/<rid>')
    def delete(rid):
        with store.transaction() as db:
            rule = get(db, rid)
            fw.block(rule)  # Keep the actual DROP rule after removing the registry entry.
            db.execute('DELETE FROM rules WHERE id=?', (rid,))
        return jsonify(ok=True, message='App removed; its port remains blocked')

    @app.post('/rules/<rid>/<action>')
    def change(rid, action):
        if action not in ('block', 'allow', 'allow-temporary'):
            from werkzeug.exceptions import NotFound
            raise NotFound('Unknown action')
        minutes = None
        if action == 'allow-temporary':
            minutes = body().get('minutes', 30)
            if type(minutes) is not int or not 1 <= minutes <= 240:
                raise ValueError('minutes must be an integer between 1 and 240')
        # The store lock serializes registry, actions and expiry across processes.
        with store.transaction() as db:
            rule = get(db, rid)
            deadline = time.time() + minutes * 60 if minutes is not None else None
            if action == 'allow-temporary':
                fw.block(rule)
                # Commit the deadline BEFORE opening. If the process dies during
                # allow, restart still has a durable expiry to reconcile.
                db.execute('UPDATE rules SET expires_at=? WHERE id=?', (deadline, rid))
                db.commit()
                db.execute('BEGIN IMMEDIATE')
            try:
                if action == 'block':
                    fw.block(rule)
                else:
                    fw.allow(rule, persist=action == 'allow')
                db.execute('UPDATE rules SET expires_at=? WHERE id=?', (deadline, rid))
                result = serialize(get(db, rid))
                # Include commit errors in fail-closed recovery while holding lock.
                db.commit()
            except Exception:
                if action != 'block':
                    try:
                        fw.block(rule)
                    except Exception:
                        LOG.exception('CRITICAL: failed to restore DROP after failed allow')
                raise
        return jsonify(ok=True, rule=result, **({'auto_block_minutes': minutes} if minutes is not None else {}))

    return app


def start_expiry_worker(app):
    def work():
        while True:
            try:
                app.extensions['expire']()
            except Exception:
                app.logger.exception('Expiry failed; retrying in one second')
            time.sleep(1)
    # Initial reconciliation completes before the server accepts requests.
    app.extensions['expire']()
    thread = threading.Thread(target=work, name='jit-expiry', daemon=True)
    thread.start()
    return thread
