# hookshot-ps5-builder: baut mihawk-99/PS5_Hookshot (PPSA99024) aus der eigenen .nup.
# Arch Linux, weil PS5_Vulkan Arch/CachyOS als einzigen unterstuetzten Build-Host nennt.
FROM archlinux:latest

RUN pacman -Syu --noconfirm --needed \
        base-devel clang llvm llvm-libs lld libclc spirv-llvm-translator spirv-tools spirv-headers \
        make cmake meson ninja pkgconf glslang nasm bison flex \
        python python-pip git curl wget unzip tar zstd rsync util-linux which file \
        ca-certificates \
    && pacman -Scc --noconfirm

# Python-Pakete: Hookshots Lift (lz4 numpy capstone unicorn zstandard, Upstream-Liste in docs/PS5.md)
# und Mesas Generatoren (mako markupsafe pyyaml packaging), plus Pillow fuer PS5_VulkanTemplate.
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir \
        lz4 numpy capstone "unicorn>=2.1,<2.2" zstandard mako markupsafe pyyaml packaging pillow
ENV PATH="/opt/venv/bin:${PATH}" \
    CONFIG_DIR=/config \
    NUP_DIR=/nup \
    WEBUI_PORT=8484 \
    PYTHONUNBUFFERED=1

ARG GIT_SHA=unbekannt
ENV IMAGE_REV=${GIT_SHA}
COPY scripts/ /app/scripts/
COPY webui/ /app/webui/
RUN chmod +x /app/scripts/*.sh

EXPOSE 8484
VOLUME ["/config"]
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
