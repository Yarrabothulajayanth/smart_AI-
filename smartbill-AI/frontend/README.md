# SmartBill AI frontend

The React/Vite frontend setup, environment variables, security notes, and
deployment instructions are maintained in the project [README](../README.md).

Quick local start, from this directory:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm ci
npm run dev -- --host 127.0.0.1
```

The backend must be running on `127.0.0.1:8000`. Vite proxies `/api` requests
to FastAPI, keeping the browser on one origin so session cookies work without
cross-origin configuration. `VITE_API_BASE_URL` is a public API path only;
never put secrets in frontend environment variables.
