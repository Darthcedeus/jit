# API

Except `/health` and public frontend files, every request requires `Authorization: Bearer TOKEN`. Body requests use `Content-Type: application/json`. A reverse proxy may expose these routes under `/api` by stripping that prefix upstream.

| Method | Route | Behavior |
| --- | --- | --- |
| GET | `/health` | Liveness only; does not check firewall privileges |
| GET | `/rules` | List registry and current exact DROP status |
| GET | `/rules/{id}` | Read one app |
| POST | `/rules` | Create app, block port, persist registry (201) |
| PATCH | `/rules/{id}` | Change `name` and/or `description` |
| DELETE | `/rules/{id}` | Block port, clear timer, remove registry; DROP remains |
| POST | `/rules/{id}/block` | Block and cancel timer |
| POST | `/rules/{id}/allow` | Permanent allow and cancel timer |
| POST | `/rules/{id}/allow-temporary` | Allow until the new deadline; replaces old timer |

Create example:

```json
{"id":"example","name":"Example app","port":9090,"proto":"tcp","description":"My Docker app"}
```

Temporary access body: `{"minutes":30}`. Whole numbers 1–240 are accepted; omitted `minutes` defaults to 30. Out-of-range values are rejected rather than silently clamped. Other action endpoints take no body.

Rules contain `id`, `name`, `port`, `proto`, `description`, `blocked`, `allowed`, and `expires_at` (Unix timestamp seconds or null). List responses are `{"ok":true,"rules":[...]}`; individual/create/edit/action responses are `{"ok":true,"rule":{...}}`. Temporary allow also returns `auto_block_minutes`. Errors return `{"ok":false,"error":"..."}` with 400 for validation/malformed JSON, 401 for authentication, 404 for missing apps/routes, 409 for duplicate ID or port/protocol, and 503 for operational failures. HTTP framework errors retain their status (for example 405 or 413).

Names allow 1–100 characters; descriptions allow up to 500. IDs allow 1–64 ASCII letters/digits/underscores/hyphens, starting with a letter or digit. Ports are integer 1–65535 excluding configured management ports. Protocol is `tcp` or `udp`. ID, port and protocol are immutable. The registry has unique ID and unique port/protocol pairs. Unknown body fields are rejected. On restart the database is retained and the seed file is not reimported.
