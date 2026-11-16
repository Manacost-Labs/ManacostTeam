#!/usr/bin/env bash
# Деплой проекта `editorteam` (editor + adapter + studio/translator/research)
# на сервер 151.
#
#   deploy.sh <sha>     обновить рабочую копию до <sha>, собрать, поднять,
#                       проверить здоровье; при провале откатиться.
#
# Переменные окружения (значения по умолчанию — для сервера 151):
#   DRY_RUN=1                 печатать изменяющие команды вместо выполнения
#   MANACOST_WORKDIR          рабочая копия (/srv/projects/web/ManacostTeam)
#   EDITORTEAM_SERVER_DIR     серверные файлы (/srv/editorteam)
#   EDITORTEAM_SECRETS_DIR    секреты на tmpfs (/run/editorteam)
#   DEPLOY_REMOTE             git remote (origin)
#   MIN_FREE_GB               минимум свободного места для сборки (6)
#   HEALTH_TIMEOUT            секунд ожидания здоровья на сервис (300)
#   DEPLOY_LOCK_FILE          файл блокировки (/run/lock/editorteam-deploy.lock)
#
# Коды выхода: 0 — успех; 1 — деплой не начат или провален и откат успешен;
# 2 — провалился и откат (нужно ручное вмешательство).
set -euo pipefail

WORKDIR="${MANACOST_WORKDIR:-/srv/projects/web/ManacostTeam}"
SERVER_DIR="${EDITORTEAM_SERVER_DIR:-/srv/editorteam}"
SECRETS_DIR="${EDITORTEAM_SECRETS_DIR:-/run/editorteam}"
REMOTE="${DEPLOY_REMOTE:-origin}"
MIN_FREE_GB="${MIN_FREE_GB:-6}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-300}"
LOCK_FILE="${DEPLOY_LOCK_FILE:-/run/lock/editorteam-deploy.lock}"
DRY_RUN="${DRY_RUN:-0}"

PROJECT=editorteam
SERVER_ENV="$SERVER_DIR/server.env"
SERVER_OVERLAY="$SERVER_DIR/compose.server.yml"
STUDIO_ENV="$SERVER_DIR/studio.env"
STUDIO_SECRETS="$SECRETS_DIR/studio"
STUDIO_SECRET_FILES=(oidc_client_secret session_secret source_gateway_token)
RESEARCH_ENV="$SECRETS_DIR/research.env"
STUDIO_OVERLAY_REL=deploy/151/compose.studio.yml
EXTRA_SERVICES=(studio translator research)
PRUNE_UNTIL=72h

GATEWAY_HEALTH_URL="${GATEWAY_HEALTH_URL:-http://127.0.0.1:8740/health}"
ADAPTER_HEALTH_URL="${ADAPTER_HEALTH_URL:-http://127.0.0.1:8795/health}"
STUDIO_HEALTH_URL="${STUDIO_HEALTH_URL:-http://127.0.0.1:8796/health}"

# Заполняются select_stack.
COMPOSE_FILES=()
SERVICES=()
ENABLED_EXTRAS=()

log() { printf '[deploy %s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
warn() { log "ПРЕДУПРЕЖДЕНИЕ: $*"; }
die() { log "ОШИБКА: $1"; exit "${2:-1}"; }
dry() { [[ "$DRY_RUN" == 1 ]]; }

# Изменяющие команды: в сухом режиме только печатаются.
run() {
    if dry; then
        printf '+'; printf ' %q' "$@"; printf '\n'
    else
        "$@"
    fi
}

have_docker() { command -v docker >/dev/null 2>&1; }

compose() {
    run docker compose -p "$PROJECT" --env-file "$SERVER_ENV" "${COMPOSE_FILES[@]}" "$@"
}

# Чтение состояния; в сухом режиме без docker — пусто.
compose_query() {
    if dry && ! have_docker; then
        return 0
    fi
    docker compose -p "$PROJECT" --env-file "$SERVER_ENV" "${COMPOSE_FILES[@]}" "$@"
}

contains() {
    local needle=$1; shift
    local item
    for item in "$@"; do [[ "$item" == "$needle" ]] && return 0; done
    return 1
}

usage() {
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//' >&2
    exit 1
}

# ---------------------------------------------------------------- блокировка
acquire_lock() {
    if ! command -v flock >/dev/null 2>&1; then
        dry && { warn "flock недоступен, сухой режим идёт без блокировки"; return 0; }
        die "flock не найден (пакет util-linux)"
    fi
    exec 9>"$LOCK_FILE" || die "не удалось открыть $LOCK_FILE"
    if ! flock -w 1800 9; then
        die "другой деплой держит $LOCK_FILE дольше 30 минут"
    fi
}

# ---------------------------------------------------------------- место на диске
docker_root() {
    local root=""
    if have_docker; then
        root=$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || true)
    fi
    [[ -n "$root" && -d "$root" ]] || root=/
    printf '%s\n' "$root"
}

free_gb() {
    df -BG --output=avail "$(docker_root)" | tail -n 1 | tr -dc '0-9'
}

prune_docker() {
    run docker builder prune -f --filter "until=$PRUNE_UNTIL"
    run docker image prune -f
}

ensure_disk_space() {
    local free
    free=$(free_gb)
    log "свободно ${free} ГБ на $(docker_root) (нужно не меньше ${MIN_FREE_GB})"
    (( free >= MIN_FREE_GB )) && return 0
    log "мало места: чищу build cache старше $PRUNE_UNTIL и висячие образы"
    prune_docker
    dry && return 0
    free=$(free_gb)
    log "после уборки свободно ${free} ГБ"
    (( free >= MIN_FREE_GB )) \
        || die "свободно ${free} ГБ < ${MIN_FREE_GB} ГБ; деплой не начат, ничего не менялось"
}

# ---------------------------------------------------------------- git
git_wc() { git -C "$WORKDIR" "$@"; }

ensure_clean_worktree() {
    if ! git_wc diff --quiet || ! git_wc diff --cached --quiet; then
        git_wc status --short --untracked-files=no >&2 || true
        die "в $WORKDIR есть незакоммиченные правки отслеживаемых файлов; деплой остановлен"
    fi
}

checkout_commit() {
    local sha=$1
    run git -C "$WORKDIR" -c advice.detachedHead=false checkout --detach "$sha"
}

# ---------------------------------------------------------------- состав стека
# Решает, какие файлы и сервисы участвуют, исходя из текущего дерева рабочей
# копии и наличия env/секретов на сервере.
select_stack() {
    COMPOSE_FILES=(-f "$WORKDIR/editor/docker-compose.yml" -f "$SERVER_OVERLAY")
    ENABLED_EXTRAS=()

    local overlay="$WORKDIR/$STUDIO_OVERLAY_REL"
    if [[ ! -f "$overlay" ]]; then
        warn "нет $STUDIO_OVERLAY_REL в этой ревизии: studio, translator и research пропущены"
    else
        COMPOSE_FILES+=(-f "$overlay")
        ENABLED_EXTRAS+=(translator)

        if [[ -s "$RESEARCH_ENV" ]] && grep -q '^SOURCE_GATEWAY_TOKEN=.' "$RESEARCH_ENV" 2>/dev/null; then
            ENABLED_EXTRAS+=(research)
        else
            warn "нет $RESEARCH_ENV с SOURCE_GATEWAY_TOKEN: research пропущен"
        fi

        local missing=() name
        [[ -s "$STUDIO_ENV" ]] || missing+=("$STUDIO_ENV")
        for name in "${STUDIO_SECRET_FILES[@]}"; do
            [[ -s "$STUDIO_SECRETS/$name" ]] || missing+=("$STUDIO_SECRETS/$name")
        done
        if (( ${#missing[@]} == 0 )); then
            ENABLED_EXTRAS+=(studio)
        else
            warn "studio пропущена, не хватает: ${missing[*]}"
        fi
    fi

    # Базовые сервисы — всё, что описано в editor/docker-compose.yml и
    # серверном оверлее (adapter и т. п.); дополнительные — только включённые.
    local base
    if dry && ! have_docker; then
        base=$'analyzer\ngateway\nlanguagetool\nnlp\nadapter'
        warn "docker недоступен: состав базовых сервисов в сухом режиме условный"
    else
        base=$(docker compose -p "$PROJECT" --env-file "$SERVER_ENV" \
            -f "$WORKDIR/editor/docker-compose.yml" -f "$SERVER_OVERLAY" config --services) \
            || return 1
    fi
    mapfile -t SERVICES <<<"$base"
    SERVICES+=("${ENABLED_EXTRAS[@]}")
    log "сервисы: ${SERVICES[*]}"
}

# Если в ревизии нет оверлея студии (например, откат на ревизию до его
# появления), убирает контейнеры studio/translator/research, оставшиеся от
# неудачной попытки. Когда оверлей есть, а сервис пропущен из-за env/секретов,
# прежний контейнер не трогаем: его состав мог быть рабочим.
remove_disabled_extras() {
    [[ -f "$WORKDIR/$STUDIO_OVERLAY_REL" ]] && return 0
    local svc ids
    for svc in "${EXTRA_SERVICES[@]}"; do
        if dry && ! have_docker; then
            log "[dry] удалил бы контейнеры $svc проекта $PROJECT, если есть"
            continue
        fi
        ids=$(docker ps -aq \
            --filter "label=com.docker.compose.project=$PROJECT" \
            --filter "label=com.docker.compose.service=$svc")
        [[ -z "$ids" ]] && continue
        log "удаляю $svc: его нет в этой ревизии"
        # shellcheck disable=SC2086
        run docker rm -f $ids >/dev/null || return 1
    done
}

# ---------------------------------------------------------------- здоровье
wait_http() {
    local name=$1 url=$2
    if dry; then
        log "[dry] ждал бы $name: $url"
        return 0
    fi
    local deadline=$((SECONDS + HEALTH_TIMEOUT))
    until curl -fsS -o /dev/null --max-time 5 "$url"; do
        if (( SECONDS >= deadline )); then
            log "$name: нет ответа 200 от $url за ${HEALTH_TIMEOUT} с"
            return 1
        fi
        sleep 5
    done
    log "$name: здоров ($url)"
}

wait_container() {
    local svc=$1
    if dry; then
        log "[dry] ждал бы healthcheck контейнера $svc"
        return 0
    fi
    local deadline=$((SECONDS + HEALTH_TIMEOUT)) cid status
    while :; do
        cid=$(compose_query ps -q "$svc" 2>/dev/null | head -n1 || true)
        status=missing
        if [[ -n "$cid" ]]; then
            status=$(docker inspect -f \
                '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
                "$cid" 2>/dev/null || echo missing)
        fi
        case "$status" in
            healthy) log "$svc: здоров"; return 0 ;;
        esac
        if (( SECONDS >= deadline )); then
            log "$svc: состояние '$status' через ${HEALTH_TIMEOUT} с"
            compose_query logs --no-color --tail 40 "$svc" >&2 || true
            return 1
        fi
        sleep 5
    done
}

check_health() {
    local failed=0
    wait_http gateway "$GATEWAY_HEALTH_URL" || failed=1
    wait_http adapter "$ADAPTER_HEALTH_URL" || failed=1
    if contains studio "${ENABLED_EXTRAS[@]}"; then
        wait_http studio "$STUDIO_HEALTH_URL" || failed=1
    fi
    local svc
    for svc in translator research; do
        if contains "$svc" "${ENABLED_EXTRAS[@]}"; then
            wait_container "$svc" || failed=1
        fi
    done
    return "$failed"
}

# ---------------------------------------------------------------- сборка и запуск
# Сборка идёт, пока старые контейнеры работают; `up -d` пересоздаёт только
# изменившиеся сервисы, поэтому простой gateway — секунды на пересоздание.
# --remove-orphans не используется: чужие и временно выключенные сервисы
# проекта не трогаем, лишние дополнительные убирает remove_disabled_extras.
build_and_up() {
    select_stack || return 1
    compose build "${SERVICES[@]}" || return 1
    remove_disabled_extras || return 1
    compose up -d "${SERVICES[@]}" || return 1
    check_health
}

cleanup() {
    log "уборка: build cache старше $PRUNE_UNTIL и висячие образы"
    prune_docker || warn "уборка docker не удалась"
    df -h / >&2 || true
}

# ---------------------------------------------------------------- основной сценарий
deploy() {
    local target=$1

    [[ -d "$WORKDIR/.git" || -f "$WORKDIR/.git" ]] || die "$WORKDIR не git-репозиторий"
    [[ -f "$SERVER_ENV" ]] || dry || die "нет $SERVER_ENV"
    [[ -f "$SERVER_OVERLAY" ]] || dry || die "нет $SERVER_OVERLAY"

    acquire_lock
    ensure_disk_space
    ensure_clean_worktree

    local prev
    prev=$(git_wc rev-parse HEAD)
    log "текущая ревизия: $prev"

    run git -C "$WORKDIR" fetch --quiet "$REMOTE"
    local sha
    if ! sha=$(git_wc rev-parse --verify --quiet "${target}^{commit}"); then
        dry || die "ревизия $target не найдена после fetch $REMOTE"
        sha=$target
    fi
    log "цель: $sha"

    checkout_commit "$sha"
    if build_and_up; then
        log "деплой $sha успешен"
        cleanup
        return 0
    fi

    log "деплой $sha провалился, откатываюсь на $prev"
    checkout_commit "$prev"
    if build_and_up; then
        cleanup
        die "деплой $sha провалился; откат на $prev выполнен, сервисы здоровы" 1
    fi
    die "деплой $sha провалился, и откат на $prev тоже не прошёл проверку здоровья — нужна ручная проверка" 2
}

main() {
    [[ $# -eq 1 && -n "$1" && "$1" != -* ]] || usage
    dry && log "СУХОЙ РЕЖИМ: изменяющие команды только печатаются"
    command -v git >/dev/null 2>&1 || die "git не найден"
    dry || have_docker || die "docker не найден"
    dry || command -v curl >/dev/null 2>&1 || die "curl не найден"
    deploy "$1"
}

main "$@"
