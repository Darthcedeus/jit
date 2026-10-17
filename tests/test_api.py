import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from jit_firewall import create_app

NEW = dict(id='my-app', name='My App', port=9090, proto='tcp', description='Example')

def test_auth_and_seed(setup):
    app, client, fw, config = setup
    assert app.test_client().get('/rules').status_code == 401
    assert app.test_client().post('/rules', json=NEW).status_code == 401
    assert app.test_client().get('/health').status_code == 200
    assert app.test_client().get('/').status_code == 200
    assert len(client.get('/rules').json['rules']) == 0
    with pytest.raises(ValueError):
        create_app(dict(config, API_TOKEN='test123'), fw)

def test_create_edit_delete_and_restart(setup):
    app, client, fw, config = setup
    response = client.post('/rules', json=NEW)
    assert response.status_code == 201 and response.json['rule']['blocked']
    assert client.post('/rules', json=NEW).status_code == 409
    assert client.post('/rules', json=dict(NEW, id='duplicate')).status_code == 409
    assert client.patch('/rules/my-app', json={'name': 'Changed'}).json['rule']['name'] == 'Changed'
    assert client.patch('/rules/my-app', json={'port': 9091}).status_code == 400
    restarted = create_app(config, fw).test_client()
    restarted.environ_base.update(client.environ_base)
    assert restarted.get('/rules/my-app').json['rule']['name'] == 'Changed'
    client.post('/rules/my-app/allow')
    assert not fw.blocked(NEW)
    assert client.delete('/rules/my-app').status_code == 200 and fw.blocked(NEW)
    assert client.get('/rules/my-app').status_code == 404

@pytest.mark.parametrize('fields', [
    {'port': 22}, {'port': 8765}, {'port': 9080}, {'port': 0},
    {'port': 65536}, {'port': '9090'}, {'port': True}, {'port': 9090.5},
    {'proto': 'tcp; whoami'}, {'proto': 'icmp'}, {'id': "x');alert(1)//"},
    {'id': '../x'}, {'name': ''}, {'name': 1}, {'description': []}, {'extra': 1},
])
def test_validation(setup, fields):
    _, client, fw, _ = setup
    assert client.post('/rules', json=dict(NEW, **fields)).status_code == 400
    assert not fw.drops

def test_temporary_access_renew_cancel_expire_and_restart(setup, monkeypatch):
    app, client, fw, config = setup
    client.post('/rules', json=NEW)
    now = time.time()
    monkeypatch.setattr('jit_firewall.time.time', lambda: now)
    first = client.post('/rules/my-app/allow-temporary', json={'minutes': 1}).json['rule']
    assert first['expires_at'] == now+60 and first['allowed']
    now += 30
    renewed = client.post('/rules/my-app/allow-temporary', json={'minutes': 2}).json['rule']
    now += 31
    restarted = create_app(config, fw)
    restarted.extensions['expire']()
    assert not fw.blocked(NEW)
    now = renewed['expires_at']+1
    restarted.extensions['expire']()
    assert fw.blocked(NEW)
    assert client.get('/rules/my-app').json['rule']['expires_at'] is None
    client.post('/rules/my-app/allow-temporary', json={'minutes': 1})
    client.post('/rules/my-app/allow')
    now += 120
    app.extensions['expire']()
    assert not fw.blocked(NEW)
    client.post('/rules/my-app/allow-temporary', json={'minutes': 1})
    client.post('/rules/my-app/block')
    assert client.get('/rules/my-app').json['rule']['expires_at'] is None

@pytest.mark.parametrize('minutes', ['30', 0, 241, 1.5, True, None, []])
def test_invalid_timer(setup, minutes):
    _, client, fw, _ = setup
    client.post('/rules', json=NEW)
    assert client.post('/rules/my-app/allow-temporary', json={'minutes': minutes}).status_code == 400
    assert fw.blocked(NEW)

def test_failures_close_and_do_not_claim_success(setup):
    app, client, fw, _ = setup
    client.post('/rules', json=NEW)
    fw.fail_allow = True
    assert client.post('/rules/my-app/allow').status_code == 503 and fw.blocked(NEW)
    fw.fail_block = True
    assert client.delete('/rules/my-app').status_code == 503
    with app.extensions['store'].transaction() as db:
        assert db.execute('SELECT id FROM rules WHERE id=?', ('my-app',)).fetchone()

def test_expiry_failure_retries(setup):
    app, client, fw, _ = setup
    client.post('/rules', json=NEW)
    client.post('/rules/my-app/allow-temporary', json={'minutes': 1})
    with app.extensions['store'].transaction() as db:
        db.execute('UPDATE rules SET expires_at=1 WHERE id=?', ('my-app',))
    fw.fail_block = True
    with pytest.raises(RuntimeError):
        app.extensions['expire']()
    fw.fail_block = False
    app.extensions['expire']()
    assert fw.blocked(NEW)

def test_cors_and_http_errors(setup):
    app, client, _, _ = setup
    app.config['CORS_ORIGINS'] = 'https://ui.example.test'
    assert client.get('/rules', headers={'Origin':'https://ui.example.test'}).headers['Access-Control-Allow-Origin'] == 'https://ui.example.test'
    assert 'Access-Control-Allow-Origin' not in client.get('/rules', headers={'Origin':'https://other.test'}).headers
    assert client.get('/missing').status_code == 404
    assert client.post('/rules', data='bad', content_type='application/json').status_code == 400
    assert client.post('/rules', json=[]).status_code == 400

def test_concurrent_duplicate_create(setup):
    app, client, fw, _ = setup
    def add(_):
        c = app.test_client()
        c.environ_base.update(client.environ_base)
        return c.post('/rules', json=NEW).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(add, range(2))) == [201,409]

def test_deadline_committed_before_kernel_is_opened(setup):
    import sqlite3
    app, client, fw, config = setup
    client.post('/rules', json=NEW)
    original = fw.allow
    def allow(rule, persist=True):
        # A separate raw connection models what survives an abrupt process exit.
        with sqlite3.connect(config['DATABASE']) as db:
            deadline = db.execute('SELECT expires_at FROM rules WHERE id=?', ('my-app',)).fetchone()[0]
            assert deadline is not None
        return original(rule, persist)
    fw.allow = allow
    assert client.post('/rules/my-app/allow-temporary', json={'minutes': 1}).status_code == 200

def test_private_seed_imports_only_on_first_start(setup, tmp_path):
    import json
    app, client, fw, config = setup
    seed = tmp_path / 'example-seed.json'
    seed.write_text(json.dumps([NEW]))
    config = dict(config, DATABASE=str(tmp_path / 'seeded.sqlite3'), SEED=str(seed))
    seeded = create_app(config, fw).test_client()
    seeded.environ_base.update(client.environ_base)
    assert seeded.get('/rules/my-app').status_code == 200
    assert not fw.blocked(NEW)  # Seed import never changes kernel state.
    seed.write_text('[]')
    restarted = create_app(config, fw).test_client()
    restarted.environ_base.update(client.environ_base)
    assert restarted.get('/rules/my-app').status_code == 200
