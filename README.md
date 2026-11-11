# hookshot-ps5-builder

Unraid-Container, der [mihawk-99/PS5_Hookshot](https://github.com/mihawk-99/PS5_Hookshot) baut: *The Legend of Zelda:
Ocarina of Time* (Switch-2-Version), statisch rekompiliert, als natives PS5-Homebrew-Title **PPSA99024**. Aus der eigenen
`.nup`, auf dem eigenen Server. Anschließend kopiert er das Title per FTP auf die PS5.

Im Image sind weder Spieldateien noch Keys oder Builds. Es enthält nur die Build-Werkzeuge. Lift, Objekte und
`dist/PPSA99024` entstehen unter `/config` und bleiben dort.

## Was er macht

| Stufe | Inhalt |
| --- | --- |
| update | PS5_Hookshot auf `HOOKSHOT_REF` (Standard `latest`: das neueste `ps5-v*`-Release), PS5_Vulkan, PS5_Mesa, PS5_PayloadSDK und PS5_MihawkGen auf die Revisionen, die `ps5/build-title.sh` dieses Stands pinnt |
| build | das offizielle `ps5/build-title.sh <nup> --jobs N`: SDK, native Tool, libc.prx, RADV, Header, Lift, FFmpeg, zstd, Kompilieren und Linken zu `dist/PPSA99024` |
| deploy | `dist/PPSA99024` nach `/data/homebrew/PPSA99024`, nur geänderte Dateien; prüft, ob die `.nup` dort liegt, wo Hookshot sie sucht |

## Voraussetzungen

- Unraid mit rund 60 GB frei unter `/config` (Upstream-Angabe für den Build). Am besten auf den Cache legen.
- Die eigene `.nup` von Ocarina of Time in genau dieser Version: `0400486024DEC000`, Update v131072, Build `e0f3ccfa`
  (siehe Upstream-README).
- Eine PS5 mit Homebrew-Umgebung. PS5_Vulkan wurde mit etaHEN, ShadowMountPlus (startet Titles unter
  `/data/homebrew`) und ftpsrv auf Port 2121 getestet.
- Die romfs liest Hookshot auf der Konsole direkt aus der `.nup`, und zwar nur an festen Orten:
  `ps5-v0.1.0-beta.1` unter `/data/prosperoeden/roms/oot/oot.nup`, neuere Stände zuerst unter
  `/data/lichii/roms/oot/oot.nup`. `HOS_PS5_NUP` in `hookshot_env.txt` wirkt nicht, weil die Datei keine Pfade annimmt.
  Fehlt die Datei dort, stürzt das Title beim Start mit SIGSEGV ab. Eine `.nup` von PS5_Lichii lässt sich per FTP
  dorthin verschieben, Lichii findet sie unter jedem Namen in `roms/`. Mit `UPLOAD_NUP=true` kopiert das Deploy die
  Datei nach `PS5_NUP_PATH`, fortsetzbar.

## Installation (Unraid)

```bash
mkdir -p /boot/config/plugins/dockerMan/templates-user
curl -fsSL -o /boot/config/plugins/dockerMan/templates-user/my-hookshot-ps5-builder.xml \
  https://raw.githubusercontent.com/cosmicflow2512/hookshot-ps5-builder/main/unraid/hookshot-ps5-builder.xml
```

Danach unter Docker → Add Container das Template `hookshot-ps5-builder` wählen, `PS5_HOST` eintragen und die Web-UI
öffnen (Port 8484).

## Speicher

Das Template begrenzt den Container mit `--memory=8g --memory-swap=8g` (Extra Parameters). Das Limit muss unter dem RAM liegen, der auf dem Host
tatsächlich frei ist (`free -m`, Spalte available), sonst geht dem Host der Speicher vorher aus. Läuft der Build über
das Limit, beendet der Kernel nur einen Compiler im Container und nicht Prozesse des Hosts. Unraid läuft aus dem RAM
und hat normalerweise keinen Swap, deshalb ist das Limit wichtig. Ein abgebrochener Build lässt sich einfach neu
starten, `ps5/build.py` kompiliert nur, was fehlt.

## Spielstände von PS5_Lichii

„Spielstände anzeigen“ listet per FTP die OoT-Saves von PS5_Lichii (`/data/lichii/user`, ältere Stände
`/data/prosperoeden/user`, Edens Pfad `nand/user/save/…/0400486024DEC000/`) und den von Hookshot
(`/data/homebrew/PPSA99024/user/save/<uid>/`). „Lichii-Saves übernehmen“ kopiert die slot_*-Ordner, `account.sav` und
`option.sav` des zuletzt gespeicherten Lichii-Saves zu Hookshot, wie `scripts/oot_saves.py` von PS5_Hookshot. Das
Hookshot-Save wird vorher nach `/config/save-backup/<zeit>/` gesichert. `SAVE_FROM` wählt einen anderen Lichii-Ordner.
Hookshot darf dabei nicht laufen.

## Spieloptionen

Der Reiter „Spieloptionen“ in der Web-UI liest und schreibt per FTP die drei Dateien, die Hookshot im Title-Ordner
beim Start liest: `language.txt` (Spielsprache), `hookshot_options.ini` (die Zeilen des Insert-Menüs) und
`hookshot_env.txt` (Schalter). Jede Option hat eine Erklärung und, wo es die PS5 betrifft, einen Hinweis. Quellen sind
`gpu/vk/vk_menu.h`, `gpu/vk/vk_menu.cpp`, `host/nn_applet.c`, `readme.md`, `docs/development.md` und `docs/PS5.md` von
PS5_Hookshot. Nur PC-Optionen (Vollbild, GPU-Wahl, DLSS, Reflex, HDR, Maus, Mikrofon, Discord, Bewegungssteuerung) fehlen.
Zwischenbilder, Bildtaktung und das Handheld-Profil stehen bei den Schaltern: die Konsole gibt sie in `host/hos_main.c`
per Umgebung vor, und die geht über die ini.
Die Steuerungszeilen (`pad_`, `key_`) und unbekannte Zeilen der ini bleiben beim Schreiben erhalten. Hookshot vorher
beenden.

Im Spiel selbst öffnet Touchpad-Klick + Options auf dem DualSense dasselbe Insert-Menü (`host/nn_hid.c`,
`host/ps5/hos_sdl_ps5.c`: Touchpad ist Back, Options ist Start).

## Variablen

| Variable | Standard | Bedeutung |
| --- | --- | --- |
| `NUP_FILE` | leer | Pfad der `.nup` im Container. Leer heißt: erste `.nup` mit `0400486024DEC000` im Namen unter `/nup` |
| `PS5_HOST` | leer | IP der PS5 |
| `PS5_FTP_PORT` | `2121` | FTP-Port |
| `HOOKSHOT_REF` | `latest` | `latest` = neuestes `ps5-v*`-Release, `main` = Entwicklungsstand, oder ein Tag/Commit |
| `PS5_NUP_PATH` | `/data/prosperoeden/roms/oot/oot.nup` | Ziel für `UPLOAD_NUP` |
| `UPLOAD_NUP` | `false` | `.nup` beim Deploy mitkopieren |
| `AUTO_DEPLOY` | `false` | nach „Alles bauen“ automatisch deployen |
| `RUN_ON_START` | `false` | beim Containerstart sofort bauen |
| `JOBS` | Kerne − 2, höchstens (freier RAM bzw. Speicherlimit) ÷ 4 GB | parallele Compiler-Jobs |
| `FORCE_DEPLOY` | `false` | alle Dateien neu hochladen |

Kommandozeile ohne Web-UI: `docker exec -it hookshot-ps5-builder /app/scripts/build.sh all` (oder `update`,
`build`, `deploy`).

## Stand von PS5_Hookshot

Experimentell. Laut `docs/PS5.md` (Stand 10.11.2026) ist es auf einer PS5 Pro bis Kokiri-Wald getestet, mit 33–40 fps
nativ. Offen sind Speicher, der unter Last ausgeht, Ruckler bei neuen Shadern, Bewegungssteuerung und Mikrofon.

## Lizenz

GPL-3.0-or-later, wie PS5_Hookshot. Das Icon stammt aus PS5_Hookshot (`ps5/sce_sys/icon0.png`).
