#!/usr/bin/env sh
# EC2-only regression using the exact deployed Robot Shop web image.
set -eu

template=${1:-K8s/helm/files/web-default.conf.template}
port=${TS_NGINX_TEST_PORT:-18080}
image='robotshop/rs-web@sha256:b3c20d4a22f2875397726d2184062360bb2ab9c8776beffca7c2e7b3652893bc'
name="ts-nginx-attribution-$$"
backend="${name}-backend"
network="${name}-net"

[ -f "$template" ] || { echo "missing template: $template" >&2; exit 2; }
docker image inspect "$image" >/dev/null
if ss -ltn "sport = :$port" | grep -q LISTEN; then
    echo "test port $port is already listening" >&2
    exit 2
fi
cleanup() {
    docker rm -f "$name" "$backend" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM
cleanup
docker network create "$network" >/dev/null

# The backend uses the same cached image and serves only its static root. The
# test listener is published on workstation loopback; neither container joins
# a project network or contacts a project service.
docker run -d --rm --name "$backend" --network "$network" \
    -e CATALOGUE_HOST='[::1]' -e USER_HOST='[::1]' \
    -e CART_HOST='[::1]' -e SHIPPING_HOST='[::1]' \
    -e PAYMENT_HOST='[::1]' -e RATINGS_HOST='[::1]' \
    "$image" >/dev/null
docker run -d --rm --name "$name" -p "127.0.0.1:$port:8080" \
    --network "$network" \
    -e CATALOGUE_HOST="$backend" -e USER_HOST="$backend" \
    -e CART_HOST="$backend" -e SHIPPING_HOST="$backend" \
    -e PAYMENT_HOST="$backend" -e RATINGS_HOST="$backend" \
    -v "$(pwd)/$template:/etc/nginx/conf.d/default.conf.template:ro" \
    "$image" >/dev/null

tries=0
until curl -fsS --max-time 2 "http://127.0.0.1:$port/" >/dev/null 2>&1; do
    tries=$((tries + 1))
    [ "$tries" -lt 10 ] || { echo "isolated nginx did not become ready" >&2; exit 1; }
    sleep 1
done

base="http://127.0.0.1:$port"
for service in cart catalogue payment; do
    for path in "/api/$service/" "//api/$service/"; do
        code=$(curl --path-as-is -sS --max-time 5 -o /dev/null -w '%{http_code}' "$base$path")
        [ "$code" = 200 ] || { echo "$service success path returned $code" >&2; exit 1; }
    done
    for path in "/api/$service" "/api/$service?fixed=1"; do
        code=$(curl --path-as-is -sS --max-time 5 -o /dev/null -w '%{http_code}' "$base$path")
        [ "$code" = 301 ] || { echo "$service boundary path returned $code" >&2; exit 1; }
    done
done

# Restart the exact web image with unreachable loopback upstreams so the same
# single- and double-slash requests produce immediate, deterministic 502s.
success_logs=$(docker logs "$name" 2>&1 | grep '"event":"http_access"')
docker rm -f "$name" "$backend" >/dev/null
docker run -d --rm --name "$name" -p "127.0.0.1:$port:8080" \
    --network "$network" \
    -e CATALOGUE_HOST='[::1]' -e USER_HOST='[::1]' \
    -e CART_HOST='[::1]' -e SHIPPING_HOST='[::1]' \
    -e PAYMENT_HOST='[::1]' -e RATINGS_HOST='[::1]' \
    -v "$(pwd)/$template:/etc/nginx/conf.d/default.conf.template:ro" \
    "$image" >/dev/null
tries=0
until curl -fsS --max-time 2 "$base/" >/dev/null 2>&1; do
    tries=$((tries + 1))
    [ "$tries" -lt 10 ] || { echo "failure fixture did not become ready" >&2; exit 1; }
    sleep 1
done
for service in cart catalogue payment; do
    for path in "/api/$service/failure" "//api/$service/failure"; do
        code=$(curl --path-as-is -sS --max-time 5 -o /dev/null -w '%{http_code}' "$base$path")
        [ "$code" = 502 ] || { echo "$service failure path returned $code" >&2; exit 1; }
    done
done

failure_logs=$(docker logs "$name" 2>&1 | grep '"event":"http_access"')
logs=$(printf '%s\n%s\n' "$success_logs" "$failure_logs")
for service in cart catalogue payment; do
    [ "$(printf '%s\n' "$logs" | grep -Ec '"target_service":"'"$service"'".*"status":"200"')" -eq 2 ] || {
        echo "unexpected successful-route attribution for $service" >&2; exit 1; }
    [ "$(printf '%s\n' "$logs" | grep -Ec '"target_service":"'"$service"'".*"status":"301"')" -eq 2 ] || {
        echo "unexpected boundary-route attribution for $service" >&2; exit 1; }
    [ "$(printf '%s\n' "$logs" | grep -Ec '"target_service":"'"$service"'".*"status":"502"')" -eq 2 ] || {
        echo "unexpected error-route attribution for $service" >&2; exit 1; }
done
if printf '%s\n' "$logs" | grep -E '"(uri|request_uri|request|headers?)"' >/dev/null; then
    echo "request data was emitted in structured access logs" >&2
    exit 1
fi

echo "PASS: exact web image preserves normalized API attribution without request data"
