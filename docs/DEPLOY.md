# Deploy AgentMemory behind Traefik

This guide deploys AgentMemory as a remote MCP + HTTP service on a server
that already runs Traefik (for example, the `andrewm.ru` ingress host).

The public URL after setup is:

```
https://andrewm.ru/agentmemory/
```

with these paths:

- `GET  /agentmemory/health` — liveness probe (open)
- `POST /agentmemory/mcp` — MCP over HTTP (bearer-token protected)
- `POST /agentmemory/add|search|update` — legacy HTTP API (bearer-token protected)
- `GET  /agentmemory/memories`, `/agentmemory/admin/...` — admin/read APIs (bearer-token protected)

The browser UI is disabled on remote deployments via `AGENTMEMORY_DISABLE_UI=1`.

## 1. Prepare the server

Pick a directory, for example `/opt/agentmemory`, and clone the repo there:

```bash
mkdir -p /opt/agentmemory
cd /opt/agentmemory
git clone <your-repo-url> .
```

## 2. Create `.env`

Generate a strong token and write the `.env`:

```bash
cp .env.example .env
TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
sed -i "s|^AGENTMEMORY_API_TOKEN=.*|AGENTMEMORY_API_TOKEN=$TOKEN|" .env
sed -i "s|^AGENTMEMORY_DISABLE_UI=.*|AGENTMEMORY_DISABLE_UI=1|" .env
# optional, only needed for the mem0 provider
# sed -i "s|^OPENROUTER_API_KEY=.*|OPENROUTER_API_KEY=<your-key>|" .env
echo "API token: $TOKEN"
```

Save the printed token — MCP/HTTP clients need it.

## 3. Start the container

The deploy compose file binds port `18765` to the `172.30.0.1` docker
bridge gateway that Traefik uses for file-provider services (mirroring the
existing `marzban`, `subscription-builder`, etc. pattern), so the port
stays off the public interface.

```bash
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build
docker logs agentmemory --tail 30
curl -s http://172.30.0.1:18765/health
```

The `/health` call should return `{"ok": true}` without a token.

## 4. Plug into Traefik

Copy the file-provider route into Traefik's dynamic config directory:

```bash
cp deploy/traefik-agentmemory.yml /root/netbird/traefik-conf/agentmemory.yml
```

Traefik watches this directory (`--providers.file.watch=true`), so no
restart is required. Verify from the host:

```bash
curl -s https://andrewm.ru/agentmemory/health
# -> {"ok": true}
```

## 5. Smoke-test the MCP endpoint

```bash
TOKEN="..."  # from step 2

curl -sS https://andrewm.ru/agentmemory/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}'

curl -sS https://andrewm.ru/agentmemory/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

The first call returns `serverInfo`; the second lists the memory tools.

## 6. Connect a remote MCP client

### Claude (Desktop or claude.ai Custom Connectors)

Add a Custom Connector with:

- **Type:** Remote MCP / HTTP
- **URL:** `https://andrewm.ru/agentmemory/mcp`
- **Header:** `Authorization: Bearer <token>`

### ChatGPT (Custom Connectors — MCP over HTTP)

Add a connector with:

- **Server URL:** `https://andrewm.ru/agentmemory/mcp`
- **Authentication:** Custom header `Authorization: Bearer <token>`

ChatGPT requires HTTPS; the Let's Encrypt cert on `andrewm.ru` covers it.

## Updating the deployment

```bash
cd /opt/agentmemory
git pull
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build
```

## Rotating the token

```bash
NEW="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
sed -i "s|^AGENTMEMORY_API_TOKEN=.*|AGENTMEMORY_API_TOKEN=$NEW|" .env
docker compose -f deploy/docker-compose.yml --env-file .env up -d
```

Update the connector config in each client with the new token.
