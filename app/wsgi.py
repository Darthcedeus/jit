from jit_firewall import create_app, start_expiry_worker

app = create_app()
start_expiry_worker(app)
