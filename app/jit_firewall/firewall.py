"""The only module that invokes privileged commands; never uses a shell."""
import subprocess


class FirewallError(RuntimeError):
    pass


class Firewall:
    def __init__(self, chain='FORWARD', run=subprocess.run):
        if chain not in ('FORWARD', 'DOCKER-USER'):
            raise ValueError('JIT_CHAIN must be FORWARD or DOCKER-USER')
        self.chain, self.run = chain, run

    def command(self, rule, operation):
        return ['sudo', '-n', '/usr/sbin/iptables', '-w', '5', operation,
                self.chain, *(['1'] if operation == '-I' else []),
                '-p', rule['proto'], '-m', 'conntrack',
                '--ctorigdstport', str(rule['port']), '-j', 'DROP']

    def execute(self, command):
        try:
            return self.run(command, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise FirewallError('Firewall command could not complete') from error

    def checked(self, command):
        result = self.execute(command)
        if result.returncode:
            raise FirewallError('Firewall command failed; inspect server logs and sudo permissions')

    def blocked(self, rule):
        result = self.execute(self.command(rule, '-C'))
        if result.returncode not in (0, 1) or (result.returncode == 1 and result.stderr and 'Bad rule' not in result.stderr):
            raise FirewallError('Cannot inspect firewall state')
        return result.returncode == 0

    def save(self):
        self.checked(['sudo', '-n', '/usr/sbin/netfilter-persistent', 'save'])

    def block(self, rule):
        if not self.blocked(rule):
            self.checked(self.command(rule, '-I'))
        self.save()

    def allow(self, rule, persist=True):
        # Remove exact legacy duplicates as well; never flush any chain.
        for _ in range(100):
            if not self.blocked(rule):
                break
            self.checked(self.command(rule, '-D'))
        else:
            raise FirewallError('Too many duplicate rules; inspect the firewall')
        if persist:
            self.save()
