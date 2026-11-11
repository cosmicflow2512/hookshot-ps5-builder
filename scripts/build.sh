#!/usr/bin/env bash
# hookshot-ps5-builder: baut PS5_Hookshot mit dessen offiziellem ps5/build-title.sh.
#
#   build.sh update   PS5_Hookshot auf HOOKSHOT_REF (Standard: neuestes ps5-v*-Release), die anderen Repos auf die
#                     Revisionen, die build-title.sh dieses Stands pinnt ("played with on a console")
#   build.sh build    ps5/build-title.sh <nup> --jobs N: Toolchain, RADV, Lift, Kompilieren, Linken -> dist/PPSA99024
#   build.sh deploy   dist/PPSA99024 per FTP auf die PS5 (scripts/deploy.py)
#   build.sh saves    OoT-Spielstaende von PS5_Lichii auf der PS5 nach Hookshot uebernehmen (scripts/import_saves.py)
#   build.sh all      update + build (+ deploy bei AUTO_DEPLOY=true)
#
# Alles liegt unter $CONFIG_DIR/src (die Repos nebeneinander, wie build-title.sh es erwartet).
set -euo pipefail

CONFIG_DIR=${CONFIG_DIR:-/config}
NUP_DIR=${NUP_DIR:-/nup}
SRC="$CONFIG_DIR/src"
HS="$SRC/PS5_Hookshot"
GH=https://github.com/mihawk-99
REF=${HOOKSHOT_REF:-latest}

# Speicherbudget: das kleinere von freiem RAM und Speicherlimit des Containers (Template: 6 GB).
#  JOBS       Spiel-Dateien gleichzeitig (ps5/build.py): je 3 GB. build-title.sh rechnet 2 GB je Compiler ("ten at once
#             took 14 GB at their peak"), nimmt dafuer aber den RAM des ganzen Hosts.
#  BUILD_PAR  alles andere (RADV per ninja, FFmpeg/zstd per make -j$(nproc)): je 1 GB. Ohne Grenze startet ninja Kerne+2
#             und make so viele wie Kerne.
budget_mb() {
    local avail limit
    avail=$(awk '/^MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo 2>/dev/null || echo 0)
    limit=$(cat /sys/fs/cgroup/memory.max 2>/dev/null || echo max)
    if [[ $limit =~ ^[0-9]+$ ]]; then
        limit=$(( limit / 1024 / 1024 ))
        (( avail == 0 || limit < avail )) && avail=$limit
    fi
    echo "$avail"
}
CORES=$(/usr/bin/nproc)
default_par() {
    local cpu=$(( CORES > 2 ? CORES - 2 : 1 )) mem=$(( $(budget_mb) / 1024 ))
    (( mem < 1 )) && mem=1
    echo $(( cpu < mem ? cpu : mem ))
}
default_jobs() {
    local cpu=$(( CORES > 2 ? CORES - 2 : 1 )) mem=$(( $(budget_mb) / 3072 ))
    (( mem < 1 )) && mem=1
    echo $(( cpu < mem ? cpu : mem ))
}
# Lift (nx2/lift.py): forkt Emit-Worker, je einen pro 2 GB *freiem Host-RAM* (nx2/chunks.py emit_jobs); das
# Container-Limit sieht es nicht, und der Hauptprozess haelt selbst mehrere GB. Ein Lauf mit 3 Workern unter 6 GB wurde
# beendet (Killed). Hier: 1 (ohne Fork) unter 10 GB Budget, darueber je 2 GB nach 4 GB fuer den Hauptprozess.
default_lift_jobs() {
    local b; b=$(budget_mb)
    if (( b < 10240 )); then echo 1; else echo $(( (b - 4096) / 2048 )); fi
}
JOBS=${JOBS:-$(default_jobs)}
HOOKSHOT_LIFT_JOBS=${HOOKSHOT_LIFT_JOBS:-$(default_lift_jobs)}
BUILD_PAR=${BUILD_PAR:-$(default_par)}

log() { printf '\n==> [%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
die() { printf '\nFEHLER: %s\n' "$*" >&2; exit 1; }

ensure_repo() {   # name revision [--shallow]
    local name=$1 rev=$2 dir="$SRC/$1"
    if [[ ! -d $dir/.git ]]; then
        if [[ ${3:-} == --shallow ]]; then
            git init -q "$dir" && git -C "$dir" remote add origin "$GH/$name.git"
        else
            git clone -q "$GH/$name.git" "$dir"
        fi
    fi
    if ! git -C "$dir" cat-file -e "$rev^{commit}" 2>/dev/null; then
        if [[ ${3:-} == --shallow ]]; then
            git -C "$dir" fetch -q --depth 1 origin "$rev"
        else
            git -C "$dir" fetch -q --tags origin
        fi
    fi
    git -C "$dir" -c advice.detachedHead=false checkout -q --force --detach "$rev"
    printf '  %-20s %s  %s\n' "$name" "${rev:0:7}" "$(git -C "$dir" log -1 --format='%ad %s' --date=short "$rev" | cut -c1-80)"
}

pin() {   # NAME_REV aus build-title.sh des aktuellen PS5_Hookshot-Stands
    sed -n "s/^$1=\([0-9a-f]\{40\}\).*/\1/p" "$HS/ps5/build-title.sh"
}

stage_update() {
    log "PS5_Hookshot holen ($GH/PS5_Hookshot)"
    mkdir -p "$SRC"
    [[ -d $HS/.git ]] || git clone -q "$GH/PS5_Hookshot.git" "$HS"
    git -C "$HS" fetch -q --tags --force origin
    local ref=$REF
    if [[ $ref == latest ]]; then
        ref=$(git -C "$HS" tag -l 'ps5-v*' --sort=-v:refname | head -1)
        [[ -n $ref ]] || die "kein ps5-v*-Release-Tag gefunden (HOOKSHOT_REF=main setzen)"
    elif [[ $ref == main ]]; then
        ref=origin/main
    fi
    git -C "$HS" -c advice.detachedHead=false checkout -q --force --detach "$ref"
    printf '  %-20s %s  %s  (%s)\n' PS5_Hookshot "$(git -C "$HS" rev-parse --short HEAD)" \
        "$(git -C "$HS" log -1 --format='%ad %s' --date=short | cut -c1-80)" "$ref"
    [[ -f $HS/ps5/build-title.sh ]] || die "$ref hat kein ps5/build-title.sh"

    log "Abhaengigkeiten auf die Revisionen aus ps5/build-title.sh"
    local v m s g
    v=$(pin VULKAN_REV) m=$(pin MESA_REV) s=$(pin SDK_REV) g=$(pin MIHAWKGEN_REV)
    [[ -n $v && -n $m && -n $s && -n $g ]] || die "Pins in ps5/build-title.sh nicht gefunden"
    ensure_repo PS5_Vulkan "$v"
    ensure_repo PS5_PayloadSDK "$s"
    ensure_repo PS5_MihawkGen "$g"
    ensure_repo PS5_Mesa "$m" --shallow
}

find_nup() {
    if [[ -n ${NUP_FILE:-} ]]; then
        [[ -f $NUP_FILE ]] || die "NUP_FILE=$NUP_FILE existiert nicht"
        echo "$NUP_FILE"; return
    fi
    local found
    found=$(find "$NUP_DIR" -maxdepth 2 -type f -iname '*0400486024dec000*.nup' 2>/dev/null | head -1)
    [[ -n $found ]] || found=$(find "$NUP_DIR" -maxdepth 2 -type f -iname '*.nup' 2>/dev/null | head -1)
    [[ -n $found ]] || die "keine .nup in $NUP_DIR gefunden (NUP_FILE setzen)"
    echo "$found"
}

stage_build() {
    [[ -f $HS/ps5/build-title.sh ]] || stage_update
    local nup
    nup=$(find_nup)
    log "ps5/build-title.sh $(basename "$nup") --jobs $JOBS  (PS5_Hookshot $(git -C "$HS" describe --tags --always))"
    echo "  Teilschritte loggen nach $HS/work/build-title/*.log, bei Fehlern stehen die letzten 30 Zeilen hier."
    (cd "$HS" && export BUILD_PAR HOOKSHOT_LIFT_JOBS NINJA=/app/scripts/bin/ninja-limited PATH="/app/scripts/bin:$PATH" &&
        bash ps5/build-title.sh "$nup" --jobs "$JOBS")
    [[ -f $HS/dist/PPSA99024/eboot.bin ]] || die "dist/PPSA99024/eboot.bin fehlt nach dem Build"
    python3 -I /app/scripts/write_build_info.py "$HS" "$CONFIG_DIR/build-info.json"
    log "Fertig: $HS/dist/PPSA99024 ($(du -sh "$HS/dist/PPSA99024" | cut -f1))"
}

stage_deploy() {
    [[ -f $HS/dist/PPSA99024/eboot.bin ]] || die "kein Build vorhanden (erst build)"
    log "Deploy auf ${PS5_HOST:-?}:${PS5_FTP_PORT:-2121}"
    local args=(--dist "$HS/dist/PPSA99024")
    if [[ ${UPLOAD_NUP:-false} == true ]]; then args+=(--upload-nup "$(find_nup)"); fi
    python3 -I /app/scripts/deploy.py "${args[@]}"
}

stage=${1:-all}
mkdir -p "$CONFIG_DIR"
IMAGE_REV=${IMAGE_REV:-unbekannt}
echo "Image: ${IMAGE_REV:0:7}  Ref: $REF  Jobs: $JOBS  Parallel: $BUILD_PAR  Lift: $HOOKSHOT_LIFT_JOBS  RAM frei: $(awk '/^MemAvailable:/ {print int($2/1024/1024)}' /proc/meminfo) GB  Container-Limit: $(cat /sys/fs/cgroup/memory.max 2>/dev/null || echo ?)"
free=$(df -Pk "$CONFIG_DIR" | awk 'NR==2 {print int($4/1024/1024)}')
(( free >= 60 )) || echo "WARNUNG: nur ${free} GB frei unter $CONFIG_DIR, Upstream nennt ~60 GB fuer den Build"
case $stage in
    update) stage_update ;;
    build|toolchain|lift) stage_build ;;
    deploy) stage_deploy ;;
    saves) log "Spielstaende von Lichii nach Hookshot (auf der PS5)"; python3 -I /app/scripts/import_saves.py ;;
    check) log "Auf Updates pruefen"; python3 -I /app/scripts/check_updates.py ;;
    saves-list) python3 -I /app/scripts/import_saves.py --list ;;
    all)
        stage_update
        stage_build
        if [[ ${AUTO_DEPLOY:-false} == true ]]; then stage_deploy; fi
        ;;
    *) die "unbekannte Stufe: $stage (check|update|build|deploy|saves|saves-list|all)" ;;
esac
