# hookshot-ps5-builder

Unraid-Container, der [mihawk-99/PS5_Hookshot](https://github.com/mihawk-99/PS5_Hookshot) baut: *The Legend of Zelda:
Ocarina of Time* (Switch-2-Version), statisch rekompiliert, als natives PS5-Homebrew-Title **PPSA99024**. Aus der eigenen
`.nup`, auf dem eigenen Server. Anschließend kopiert er das Title per FTP auf die PS5.

Im Image sind weder Spieldateien noch Keys oder Builds. Es enthält nur die Build-Werkzeuge. Lift, Objekte und
`dist/PPSA99024` entstehen unter `/config` und bleiben dort.

## Was er macht

| Stufe | Inhalt | Quelle |
| --- | --- | --- |
| update | PS5_Hookshot, PS5_Vulkan, PS5_VulkanTemplate, PS5_PayloadSDK und PS5_MihawkGen auf den neuesten `main`, PS5_Mesa auf die Revision, die PS5_Vulkan pinnt | GitHub, mihawk-99 |
| toolchain | Payload-SDK, `ps5-native-tool`, `libc.prx`, RADV-Release-Archiv, glm (`ps5/tools/bootstrap.sh` von PS5_VulkanTemplate); Vulkan-, SPIR-V- und VMA-Header in den Versionen aus `scripts/linux/deps.sh`; FFmpeg/dav1d und zstd für die Konsole | die Skripte der Projekte selbst |
| lift | `nx2/nup.py --only exefs`, `nx2/lift.py --standalone --write` | `docs/PS5.md` |
| build | `ps5/build.py`, also kompilieren und mit RADV zu `dist/PPSA99024` linken (mit PS5_MihawkGen-Frame-Generation) | `docs/PS5.md` |
| deploy | `dist/PPSA99024` nach `/data/homebrew/PPSA99024`, nur geänderte Dateien; optional die `.nup` | FTP, Port 2121 |

Die erste Toolchain-Stufe dauert lange, vor allem wegen RADV (Mesa). Danach werden nur noch die Teile neu gebaut, die
sich geändert haben.

## Voraussetzungen

- Unraid mit rund 60 GB frei unter `/config` (Upstream-Angabe für den Build). Am besten auf den Cache legen.
- Die eigene `.nup` von Ocarina of Time in genau dieser Version: `0400486024DEC000`, Update v131072, Build `e0f3ccfa`
  (siehe Upstream-README).
- Eine PS5 mit Homebrew-Umgebung. PS5_Vulkan wurde mit etaHEN, ShadowMountPlus (startet Titles unter
  `/data/homebrew`) und ftpsrv auf Port 2121 getestet.
- Die romfs liest Hookshot auf der Konsole direkt aus der `.nup`. Standardpfad ist
  `/data/prosperoeden/roms/oot/oot.nup`, einen anderen Pfad setzt `PS5_NUP_PATH`. Mit `UPLOAD_NUP=true` kopiert das
  Deploy die Datei dorthin. Das ist fortsetzbar und wird übersprungen, wenn sie schon vollständig dort liegt.

## Installation (Unraid)

```bash
mkdir -p /boot/config/plugins/dockerMan/templates-user
curl -fsSL -o /boot/config/plugins/dockerMan/templates-user/my-hookshot-ps5-builder.xml \
  https://raw.githubusercontent.com/cosmicflow2512/hookshot-ps5-builder/main/unraid/hookshot-ps5-builder.xml
```

Danach unter Docker → Add Container das Template `hookshot-ps5-builder` wählen, `PS5_HOST` eintragen und die Web-UI
öffnen (Port 8484).

## Speicher

Das Template begrenzt den Container mit `--memory=16g --memory-swap=16g` (Extra Parameters). Läuft der Build über
das Limit, beendet der Kernel nur einen Compiler im Container und nicht Prozesse des Hosts. Unraid läuft aus dem RAM
und hat normalerweise keinen Swap, deshalb ist das Limit wichtig. Ein abgebrochener Build lässt sich einfach neu
starten, `ps5/build.py` kompiliert nur, was fehlt.

## Variablen

| Variable | Standard | Bedeutung |
| --- | --- | --- |
| `NUP_FILE` | leer | Pfad der `.nup` im Container. Leer heißt: erste `.nup` mit `0400486024DEC000` im Namen unter `/nup` |
| `PS5_HOST` | leer | IP der PS5 |
| `PS5_FTP_PORT` | `2121` | FTP-Port |
| `PS5_NUP_PATH` | `/data/prosperoeden/roms/oot/oot.nup` | Pfad der `.nup` auf der PS5. Weicht er ab, wird `HOS_PS5_NUP` in `hookshot_env.txt` gesetzt |
| `UPLOAD_NUP` | `false` | `.nup` beim Deploy mitkopieren |
| `AUTO_DEPLOY` | `false` | nach „Alles bauen“ automatisch deployen |
| `RUN_ON_START` | `false` | beim Containerstart sofort bauen |
| `JOBS` | Kerne − 2, höchstens (freier RAM bzw. Speicherlimit) ÷ 4 GB | parallele Compiler-Jobs |
| `FORCE_DEPLOY` | `false` | alle Dateien neu hochladen |

Kommandozeile ohne Web-UI: `docker exec -it hookshot-ps5-builder /app/scripts/build.sh all` (oder `update`,
`toolchain`, `lift`, `build`, `deploy`).

## Stand von PS5_Hookshot

Experimentell. Laut `docs/PS5.md` (Stand 10.11.2026) ist es auf einer PS5 Pro bis Kokiri-Wald getestet, mit 33–40 fps
nativ. Offen sind Speicher, der unter Last ausgeht, Ruckler bei neuen Shadern, Bewegungssteuerung und Mikrofon.

## Lizenz

GPL-3.0-or-later, wie PS5_Hookshot. Das Icon stammt aus PS5_Hookshot (`ps5/sce_sys/icon0.png`).
