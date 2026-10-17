#!/usr/bin/env python3
"""Development launcher; use the example systemd unit for production."""
import os
from jit_firewall import create_app, start_expiry_worker

app = create_app()
if __name__ == '__main__':
    start_expiry_worker(app)
    app.run(host=os.getenv('JIT_HOST', '127.0.0.1'), port=int(os.getenv('JIT_PORT', '8765')))
