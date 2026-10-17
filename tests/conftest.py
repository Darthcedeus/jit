from pathlib import Path
import pytest
from jit_firewall import create_app

class FakeFirewall:
    def __init__(self):
        self.drops = set()
        self.fail_allow = self.fail_block = False
    def key(self, r):
        return r['port'], r['proto']
    def blocked(self, r):
        return self.key(r) in self.drops
    def block(self, r):
        if self.fail_block:
            raise RuntimeError('test failure')
        self.drops.add(self.key(r))
    def allow(self, r, persist=True):
        self.drops.discard(self.key(r))
        if self.fail_allow:
            raise RuntimeError('test save failure after opening')

@pytest.fixture
def setup(tmp_path):
    fw = FakeFirewall()
    config = dict(TESTING=True, API_TOKEN='x'*48, DATABASE=str(tmp_path/'rules.sqlite3'),
                  SEED=str(Path(__file__).resolve().parents[1]/'config/rules.seed.json'))
    app = create_app(config, fw)
    client = app.test_client()
    client.environ_base['HTTP_AUTHORIZATION'] = 'Bearer ' + config['API_TOKEN']
    return app, client, fw, config
