#!/bin/sh
# Run the app the way the supervisor does (one container, read-only root,
# SQLite in /data, memory limit from the manifest, no hub env), check that it
# migrates, serves its health check and its page, then report memory.
#   sh scripts/container_smoke.sh dist/bdh_app_*.whl
#
# The shared runtime image lacks some of this app's dependencies, so the app
# is pip-installed into an image derived from it (a stand-in for the per-app
# images the release pipeline will build) instead of being mounted at
# /app/current.
set -eu
wheel=${1:?usage: container_smoke.sh WHEEL}
app=${SMOKE_APP:?set SMOKE_APP to the app id}
# Pages to fetch after the health check (space separated); all must be 200.
paths=${SMOKE_PATHS:-/$app/}
memory=${SMOKE_MEMORY_MB:-96}
image=${RUNTIME_IMAGE:-ghcr.io/blackdiamondlodge/bdh-app-runtime:hub-api-2}
name=$app-smoke-$$
tag=bdh-app-$app-smoke:$$
work=$(mktemp -d "${PWD}/.smoke.XXXXXX")
trap 'docker rm -f "$name" >/dev/null 2>&1 || true; docker rmi -f "$tag" >/dev/null 2>&1 || true; rm -rf "$work"' EXIT

cp "$wheel" "$work/"
cat > "$work/Dockerfile" <<EOF
FROM $image
USER root
COPY *.whl /tmp/wheel/
RUN pip install --no-cache-dir /tmp/wheel/*.whl && rm -rf /tmp/wheel
USER 10001:10001
EOF
docker build -q -t "$tag" "$work" >/dev/null

token=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
docker run -d --name "$name" --memory "${memory}m" --memory-swap "${memory}m" --read-only --tmpfs /tmp \
    --mount type=volume,dst=/data \
    -e BDH_APP_ID="$app" \
    -e BDH_APP_TOKEN="$token" \
    -p 127.0.0.1::8000 "$tag" >/dev/null
port=$(docker port "$name" 8000/tcp | head -n1 | sed 's/.*://')

ok=
for _ in $(seq 1 60); do
    if curl -sf "http://127.0.0.1:$port/_bdh/health" >/dev/null; then ok=1; break; fi
    sleep 1
done
if [ -z "$ok" ]; then
    docker logs "$name" 2>&1 | tail -n 80
    echo "$app did not become healthy"; exit 1
fi
curl -sf "http://127.0.0.1:$port/_bdh/health"; echo

# Requests signed the way the hub's proxy signs them (anonymous visitor),
# made from a sidecar in the app's network namespace so the client's memory
# isn't charged to the app's cgroup.
client() {
    docker run --rm -i --network "container:$name" -e BDH_APP_TOKEN="$token" \
        --entrypoint python "$tag" "$@"
}
hub_get() {
    client -c "
import os, sys, urllib.request
from bdh_sdk.identity import signed_headers
path = sys.argv[1]
body = b'' if path.startswith('/_bdh/') else None
req = urllib.request.Request('http://127.0.0.1:8000' + path,
                             headers=signed_headers(os.environ['BDH_APP_TOKEN'], 'GET', path, body=body))
with urllib.request.urlopen(req, timeout=30) as r:
    data = r.read()
print(r.status, len(data), 'bytes')
if body is not None:
    print(data.decode()[:2000])
" "$1"
}
hub_get /_bdh/manifest
for path in $paths; do
    if ! hub_get "$path"; then
        docker logs "$name" 2>&1 | tail -n 80
        echo "$app: GET $path failed"; exit 1
    fi
done
# App-specific checks, run inside the container (signed GETs via bdh_sdk).
extra=${SMOKE_EXTRA:-scripts/container_smoke_extra.py}
if [ -f "$extra" ] && ! client - < "$extra"; then
    docker logs "$name" 2>&1 | tail -n 80
    echo "$app: $extra failed"; exit 1
fi
sleep 5
docker logs "$name" 2>&1 | tail -n 20
if docker logs "$name" 2>&1 | grep -E "Traceback|ImportError|ModuleNotFoundError|OperationalError"; then
    echo "unexpected errors in the container log"; exit 1
fi
test "$(docker inspect -f '{{.State.Running}} {{.State.OOMKilled}}' "$name")" = "true false"
docker exec "$name" python -c "
s = dict(l.split() for l in open('/sys/fs/cgroup/memory.stat'))
cur = int(open('/sys/fs/cgroup/memory.current').read())
ws = (cur - int(s['inactive_file'])) / 2**20
def mb(f):
    try:
        return f'{int(open(\"/sys/fs/cgroup/\" + f).read()) / 2**20:.1f}MB'
    except (OSError, ValueError):
        return '?'
print(f'$app memory: working_set={ws:.1f}MB anon={int(s[\"anon\"]) / 2**20:.1f}MB '
      f'peak={mb(\"memory.peak\")} swap={mb(\"memory.swap.current\")} limit=${memory}MB')
"