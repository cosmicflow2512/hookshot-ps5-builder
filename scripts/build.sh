#!/usr/bin/env bash
# hookshot-ps5-builder: die Pipeline in Stufen.
#
#   build.sh update      Repos klonen bzw. auf den neuesten Stand ziehen (immer der aktuelle main)
#   build.sh toolchain   PS5-Payload-SDK, native Tool, libc.prx, RADV (release), FFmpeg, zstd, Header
#   build.sh lift        exefs aus der .nup holen und nach C liften (nx2/lift.py)
#   build.sh build       PPSA99024 kompilieren und linken (ps5/build.py)
#   build.sh deploy      dist/PPSA99024 per FTP auf die PS5 (scripts/deploy.py)
#   build.sh all         update + toolchain + lift + build (+ deploy bei AUTO_DEPLOY=true)
#
# Alles liegt unter $CONFIG_DIR (Standard /config): src/ (die Repos nebeneinander, wie die Skripte
# der Projekte es erwarten), logs/. Spieldateien werden nirgends hin kopiert ausser nach
# src/PS5_Hookshot/work und dist (lokal, von git ignoriert).
set -euo pipefail

CONFIG_DIR=${CONFIG_DIR:-/config}
NUP_DIR=${NUP_DIR:-/nup}
SRC="$CONFIG_DIR/src"
HS="$SRC/PS5_Hookshot"
VK="$SRC/PS5_Vulkan"
TPL="$SRC/PS5_VulkanTemplate"
MESA="$SRC/PS5_Mesa"
JOBS=${JOBS:-$(( $(nproc) > 2 ? $(nproc) - 2 : 1 ))}
GH=https://github.com/mihawk-99

log() { printf '\n==> [%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
die() { printf '\nFEHLER: %s\n' "$*" >&2; exit 1; }

# Repos, die voll geklont werden (sie pinnen Revisionen untereinander, deshalb komplette Historie)
FULL_REPOS=(PS5_Hookshot PS5_Vulkan PS5_VulkanTemplate PS5_PayloadSDK PS5_MihawkGen)

update_repo() {   # name
    local dir="$SRC/$1"
    if [[ -d $dir/.git ]]; then
        git -C "$dir" fetch -q --tags origin
        local branch
        branch=$(git -C "$dir" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')
        [[ -n $branch ]] || branch=main
        git -C "$dir" checkout -q "$branch"
        git -C "$dir" reset -q --hard "origin/$branch"
    else
        git clone -q "$GH/$1.git" "$dir"
    fi
    printf '  %-20s %s  %s\n' "$1" "$(git -C "$dir" rev-parse --short HEAD)" \
        "$(git -C "$dir" log -1 --format='%ad %s' --date=short | cut -c1-80)"
}

stage_update() {
    log "Repos aktualisieren (neuester Stand von $GH)"
    mkdir -p "$SRC"
    for r in "${FULL_REPOS[@]}"; do update_repo "$r"; done
    # PS5_Mesa ist ein Mesa-Fork (sehr grosse Historie): nur die Revision, die PS5_Vulkan pinnt.
    local pin
    pin=$(sed -n 's/^mesa_revision=\${PS5_MESA_REVISION:-\([0-9a-f]\{40\}\)}.*/\1/p' "$VK/tools/build-radv.sh")
    [[ -n $pin ]] || die "Mesa-Pin in PS5_Vulkan/tools/build-radv.sh nicht gefunden"
    if [[ ! -d $MESA/.git ]]; then
        git init -q "$MESA"
        git -C "$MESA" remote add origin "$GH/PS5_Mesa.git"
    fi
    if ! git -C "$MESA" cat-file -e "$pin^{commit}" 2>/dev/null; then
        log "PS5_Mesa: Revision ${pin:0:12} holen"
        git -C "$MESA" fetch -q --depth 1 origin "$pin"
    fi
    git -C "$MESA" checkout -q --detach "$pin"
    printf '  %-20s %s  (Pin aus PS5_Vulkan)\n' PS5_Mesa "${pin:0:7}"
}

stage_toolchain() {
    [[ -d $HS/.git && -d $VK/.git ]] || stage_update
    log "Toolchain (PS5_VulkanTemplate/ps5/tools/bootstrap.sh)"
    # bootstrap.sh zaehlt eine fehlende Konsolenadresse als offenen Punkt; die Adresse
    # braucht hier nur das Deploy, deshalb ein Eintrag, damit der Rest durchlaeuft.
    [[ -f $VK/.env ]] || printf 'PS5_HOST=%s\nFTP_PORT=%s\n' "${PS5_HOST:-0.0.0.0}" "${PS5_FTP_PORT:-2121}" > "$VK/.env"
    local out
    out=$(mktemp)
    if ! (cd "$TPL" && bash ps5/tools/bootstrap.sh) 2>&1 | tee "$out"; then
        # ps5vkctl (Steuer-Payload fuer Testlaeufe) braucht der Build nicht; alles andere schon.
        if grep -E '^  missing ' "$out" | grep -v -q 'control payload'; then
            rm -f "$out"; die "bootstrap.sh hat offene Punkte (siehe oben)"
        fi
    fi
    rm -f "$out"
    [[ -f $VK/.deps/native/radv-release/lib/libvulkan_radeon.ps5.a ]] || die "RADV-Release-Archiv fehlt"
    [[ -x $VK/build/host/ps5-native-tool && -f $VK/runtime/libc.prx ]] || die "ps5-native-tool oder libc.prx fehlt"

    log "Vulkan-, SPIR-V- und VMA-Header (Versionen aus PS5_Hookshot/scripts/linux/deps.sh)"
    local cpm="$HS/.local/ps5-deps/cpm" dl="$HS/.local/ps5-deps/downloads" vkh spv vma
    vkh=$(sed -n 's/^VK_HEADERS=\(.*\)$/\1/p' "$HS/scripts/linux/deps.sh")
    spv=$(sed -n 's/^SPIRV_HEADERS=\(.*\)$/\1/p' "$HS/scripts/linux/deps.sh")
    vma=$(sed -n 's/^VMA=\(.*\)$/\1/p' "$HS/scripts/linux/deps.sh")
    [[ -n $vkh && -n $spv && -n $vma ]] || die "Header-Versionen in scripts/linux/deps.sh nicht gefunden"
    mkdir -p "$cpm" "$dl"
    get_headers() {   # repo tag name
        [[ -d $cpm/$3/$2 ]] && { echo "  $3 $2: vorhanden"; return 0; }
        curl -fsSL --retry 5 --proto '=https' -o "$dl/$3-$2.tar.gz" "https://github.com/$1/archive/refs/tags/$2.tar.gz"
        mkdir -p "$cpm/$3/$2"
        tar -xzf "$dl/$3-$2.tar.gz" -C "$cpm/$3/$2" --strip-components=1
        echo "  $3 $2"
    }
    get_headers KhronosGroup/Vulkan-Headers "$vkh" vulkanheaders
    get_headers KhronosGroup/SPIRV-Headers "$spv" spirv-headers
    get_headers GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator "$vma" vulkanmemoryallocator

    log "FFmpeg + dav1d fuer die Konsole (ps5/tools/build-ffmpeg.sh)"
    (cd "$HS" && bash ps5/tools/build-ffmpeg.sh)
    log "zstd fuer die Konsole (ps5/tools/build-zstd.sh)"
    (cd "$HS" && bash ps5/tools/build-zstd.sh)
    log "Toolchain fertig"
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

stage_lift() {
    [[ -d $HS/.git ]] || stage_update
    local nup
    nup=$(find_nup)
    log "Spiel: $nup"
    (cd "$HS" && python3 -I nx2/nup.py "$nup")
    log "exefs extrahieren (nx2/nup.py --only exefs)"
    rm -rf "$HS/work/game"
    (cd "$HS" && python3 -I nx2/nup.py "$nup" --only exefs --extract work/game)
    log "Liften: ARM64 -> C (nx2/lift.py --standalone --write)"
    # Wie nx2/make_game.py (Upstream-Builder): lift.py schreibt die Chunk-Grenzen nach <work>/image/chunks.txt,
    # legt den Ordner aber nicht selbst an. Lifted C einer frueheren Lift-Runde vorher entfernen (Upstream #1176).
    mkdir -p "$HS/work/lift/image"
    find "$HS/work/lift/sa/gen" -maxdepth 1 -type f -name 'code_*' \
        \( -name '*.c' -o -name '*.c.whole' -o -name '*.part' \) -delete 2>/dev/null || true
    (cd "$HS" && OOT_WORK="$HS/work/lift" python3 -I nx2/lift.py --standalone --write \
        --exefs "$HS/work/game/exefs" --work "$HS/work/lift")
    [[ -f $HS/work/lift/sa/gen/a64_table.c ]] || die "Lift hat work/lift/sa/gen/a64_table.c nicht erzeugt"
    log "Lift fertig"
}

stage_build() {
    [[ -f $HS/work/lift/sa/gen/a64_table.c ]] || stage_lift
    log "PPSA99024 kompilieren und linken (ps5/build.py --jobs $JOBS)"
    (cd "$HS" && OOT_WORK="$HS/work/lift" python3 -I ps5/build.py --jobs "$JOBS")
    [[ -f $HS/dist/PPSA99024/eboot.bin ]] || die "dist/PPSA99024/eboot.bin fehlt nach dem Build"
    log "Fertig: $HS/dist/PPSA99024"
    du -sh "$HS/dist/PPSA99024"
    ls -la "$HS/dist/PPSA99024"
}

stage_deploy() {
    [[ -f $HS/dist/PPSA99024/eboot.bin ]] || die "kein Build vorhanden (erst build)"
    log "Deploy auf ${PS5_HOST:-?}:${PS5_FTP_PORT:-2121}"
    local args=(--dist "$HS/dist/PPSA99024")
    if [[ ${UPLOAD_NUP:-false} == true ]]; then args+=(--upload-nup "$(find_nup)"); fi
    python3 -I /app/scripts/deploy.py "${args[@]}"
}

check_space() {
    local free
    free=$(df -Pk "$CONFIG_DIR" | awk 'NR==2 {print int($4/1024/1024)}')
    if (( free < 60 )); then
        echo "WARNUNG: nur ${free} GB frei unter $CONFIG_DIR, Upstream nennt ~60 GB fuer den Build"
    fi
}

stage=${1:-all}
mkdir -p "$CONFIG_DIR"
check_space
case $stage in
    update) stage_update ;;
    toolchain) stage_toolchain ;;
    lift) stage_lift ;;
    build) stage_build ;;
    deploy) stage_deploy ;;
    all)
        stage_update
        stage_toolchain
        stage_lift
        stage_build
        if [[ ${AUTO_DEPLOY:-false} == true ]]; then stage_deploy; fi
        ;;
    *) die "unbekannte Stufe: $stage (update|toolchain|lift|build|deploy|all)" ;;
esac
