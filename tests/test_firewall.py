from subprocess import CompletedProcess, TimeoutExpired
import pytest
from jit_firewall.firewall import Firewall, FirewallError
RULE = dict(port=9090, proto='tcp')

def test_exact_commands_duplicate_removal_and_persistence():
    calls, drops = [], 2
    def run(cmd, **kwargs):
        nonlocal drops
        calls.append(cmd)
        if '-C' in cmd:
            return CompletedProcess(cmd, 0 if drops else 1, '', '')
        if '-D' in cmd:
            drops -= 1
        return CompletedProcess(cmd, 0, '', '')
    Firewall(run=run).allow(RULE)
    assert sum('-D' in c for c in calls) == 2
    assert calls[0] == ['sudo','-n','/usr/sbin/iptables','-w','5','-C','FORWARD','-p','tcp','-m','conntrack','--ctorigdstport','9090','-j','DROP']
    assert calls[-1] == ['sudo','-n','/usr/sbin/netfilter-persistent','save']

@pytest.mark.parametrize('code,stderr', [(2,'failed'), (1,'sudo: a password is required'), (1,'No chain/target/match by that name')])
def test_inspection_errors_never_mean_allowed(code, stderr):
    with pytest.raises(FirewallError):
        Firewall(run=lambda cmd, **kw: CompletedProcess(cmd,code,'',stderr)).blocked(RULE)

def test_temporary_allow_does_not_persist_open_port():
    calls = []
    Firewall(run=lambda cmd, **kw: (calls.append(cmd) or CompletedProcess(cmd,1,'',''))).allow(RULE, persist=False)
    assert len(calls) == 1

def test_command_timeout_and_save_failure():
    def timeout(cmd, **kw):
        raise TimeoutExpired(cmd,15)
    with pytest.raises(FirewallError):
        Firewall(run=timeout).blocked(RULE)
    with pytest.raises(FirewallError):
        Firewall(run=lambda cmd, **kw: CompletedProcess(cmd,1,'','denied')).save()
    with pytest.raises(ValueError):
        Firewall(chain='INPUT')
