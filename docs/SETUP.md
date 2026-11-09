# Setup guide: running the whole stack with Docker

This takes you from a clean machine to a running platform and a passing demo. You do **not** write or edit any Dockerfile: they are in the repo and Docker builds from them.

## What Docker does here

Docker runs each part of the system (database, Redis, Kafka, gateway, agent, worker) as an isolated container, so you don't install Java, Python, Postgres or Kafka yourself. `docker compose` reads `docker-compose.yml` and starts all six together on a private network.

## 1. Requirements

| | Minimum | Comfortable |
| --- | --- | --- |
| RAM given to Docker | 4 GB | 6-8 GB |
| Free disk | 6 GB | 10 GB |
| CPU | 2 cores | 4 cores |

Kafka and the Java gateway use the most memory. The first build downloads roughly 1.5 GB of base images and dependencies.

## 2. Install Docker

### Windows 10/11
1. Turn on virtualisation if it isn't already (Task Manager -> Performance -> CPU shows "Virtualization: Enabled"; if not, enable it in BIOS/UEFI).
2. Open PowerShell as Administrator and run `wsl --install`, then restart.
3. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and keep "Use WSL 2 based engine" ticked.
4. Give Docker enough memory: create `C:\Users\<you>\.wslconfig` containing
   ```
   [wsl2]
   memory=6GB
   processors=4
   ```
   then run `wsl --shutdown` and start Docker Desktop again.
5. **Put the project inside the WSL filesystem** (e.g. `\\wsl$\Ubuntu\home\<you>\agentic-rag-platform`) and run the commands below from an Ubuntu terminal. Builds are much faster and Windows line-ending problems disappear.

### macOS
Install Docker Desktop (Apple Silicon and Intel both work; every image used here is multi-architecture). In Docker Desktop -> Settings -> Resources, set Memory to at least 4 GB.

### Linux
Install Docker Engine and the Compose plugin from [docs.docker.com/engine/install](https://docs.docker.com/engine/install/), then:
```bash
sudo usermod -aG docker $USER    # log out and back in afterwards
```

### Check it works
```bash
docker version
docker compose version      # must print v2.x (v2.24+ if you use the production overlay)
docker run --rm hello-world
```
If `docker version` shows a "Server" section, the engine is running. If it only shows "Client", start Docker Desktop.

## 3. Get the code

Unzip it (or `git clone` your repo), then open a terminal **in the folder that contains `docker-compose.yml`**.

## 4. Start the stack

```bash
docker compose up --build -d --wait
```
- `--build` builds the gateway and Python images from their Dockerfiles.
- `-d` runs in the background.
- `--wait` returns only when every health check passes.

The first run takes **5-15 minutes** (downloads and a Maven build). Later runs take under a minute.

Check the result:
```bash
docker compose ps
```
You should see `postgres`, `redis`, `kafka`, `agent` and `gateway` as `healthy` and `worker` as `running`.

```bash
curl http://localhost:8080/actuator/health     # {"status":"UP",...}
```

## 5. Run the demo

```bash
pip install httpx          # Python 3.9+; use "py -m pip" on Windows if "pip" isn't found
python scripts/demo.py     # "python3" on macOS/Linux
```
Every line should be `PASS` and the last line `All checks passed.` It takes about 30 seconds (it deliberately pauses so the rate limiter's buckets refill before the noisy-neighbour test).

### Try it by hand
```bash
TOKEN=$(curl -s 'localhost:8080/dev/token?tenant=acme&user=alice&roles=admin&roles=employee' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -H "Authorization: Bearer $TOKEN" -F file=@sample_data/acme_handbook.md localhost:8080/api/v1/documents
curl -s -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"query":"How many weeks of parental leave?"}' localhost:8080/api/v1/query
```
(On Windows PowerShell use the WSL terminal for these, or the demo script.)

## 6. Useful commands

| Task | Command |
| --- | --- |
| See what's running | `docker compose ps` |
| Follow logs | `docker compose logs -f gateway agent worker` |
| Logs of one service | `docker compose logs --tail=100 gateway` |
| Restart one service | `docker compose restart worker` |
| Rebuild after a code change | `docker compose up --build -d --wait` |
| Stop, keep data | `docker compose down` |
| Stop and **delete all data** | `docker compose down -v` |
| Look inside the database | `docker compose exec postgres psql -U postgres -d ragdb` |

Inside psql, `\dt` lists tables and `SELECT tenant_id, filename, status FROM documents;` shows documents (as the superuser, which bypasses isolation: that is the point of the isolation tests using the restricted role instead).

## 7. Optional: real language models

By default everything runs offline with no API keys. To use a real model:
```bash
cp .env.example .env       # edit .env, then:
docker compose up -d --build
```
- Ollama (free, local): install Ollama, `ollama pull llama3.1:8b`, set `LLM_PROVIDER=ollama`.
- OpenAI: `LLM_PROVIDER=openai`, `EMBEDDING_PROVIDER=openai`, `OPENAI_API_KEY=...`
- Anthropic: `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY=...`

If you change `EMBEDDING_PROVIDER`, run `docker compose down -v` first and re-ingest your documents: vectors from different embedding models are not comparable. Never commit `.env`; it is git-ignored.

## 8. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `Cannot connect to the Docker daemon` | Docker isn't running. Start Docker Desktop (or `sudo systemctl start docker`). |
| `port is already allocated` on 8080 | Something else uses 8080. Stop it, or change `"8080:8080"` to `"8081:8080"` in `docker-compose.yml` and use `GATEWAY_URL=http://localhost:8081 python scripts/demo.py`. |
| A container shows `Exited (137)` or the build is killed | Out of memory. Raise Docker's memory limit (section 2) and retry. |
| `gateway` stays `starting` for a couple of minutes | Normal on first run (JVM start plus waiting for Kafka). `docker compose logs gateway` shows progress; `--wait` allows up to the timeout you set. |
| `gateway` unhealthy, logs mention the database or Redis | Dependencies weren't ready or crashed. `docker compose ps` to find which, then `docker compose logs <service>`. |
| `no matching manifest for linux/arm64` | You have an unusually old Docker/image combination; update Docker Desktop. All images used publish arm64. |
| `exec ... bad interpreter` / `\r` errors in the postgres logs | Windows turned line endings into CRLF. Re-clone inside WSL, or run `git config core.autocrlf input`, delete the folder and clone again. The repo's `.gitattributes` also forces LF for `.sh` files. |
| `permission denied` writing `/data/uploads` | Stale volume from an older build. `docker compose down -v` and start again. |
| Changed a password or the schema but nothing changes | Postgres only runs `db/init.sql` and `02-app-password.sh` on a brand-new volume. `docker compose down -v` wipes it (and your data). |
| `worker` keeps logging "unknown topic" at start | Expected: Kafka creates the topic on the first upload. |
| Demo says `Gateway not reachable` | Stack isn't up yet, or a different port. Check `docker compose ps`. |
| Demo step "Acme's flood is throttled" fails | Another process is using the same tenant, or you changed `RATE_LIMIT_*`. Defaults are capacity 20, refill 5/s. |
| Build fails downloading Maven/pip packages | Network or corporate proxy. Retry; behind a proxy, configure Docker Desktop's proxy settings. |

If something fails that isn't here: `docker compose logs --tail=200 > logs.txt` and read the first error, not the last.

## 9. Without Docker (not recommended)

You can run the Python tests with no Docker (`cd python && pip install -e '.[dev]' && pytest`; 45 tests run, 33 skip without Postgres/Redis). Running the full system without Docker means installing Postgres+pgvector, Redis, Kafka and JDK 21 yourself and is not documented here.
