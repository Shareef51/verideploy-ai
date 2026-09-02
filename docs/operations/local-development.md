# Local Development

## Unix-like shell
```bash
cp .env.example .env
corepack enable
pnpm install
uv sync --all-groups
docker compose up -d --build
```

## Windows PowerShell
```powershell
Copy-Item .env.example .env
corepack enable
pnpm install
uv sync --all-groups
docker compose up -d --build
```

Never commit `.env`. Replace local MinIO and application secrets before exposing any service outside localhost.
