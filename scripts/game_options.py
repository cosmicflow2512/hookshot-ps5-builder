"""Spieloptionen von Hookshot auf der PS5 lesen und schreiben, per FTP: hookshot_options.ini (das Insert-Menue),
hookshot_env.txt (Schalter) und language.txt (Sprache), alle im Title-Ordner /data/homebrew/PPSA99024.

Quellen (PS5_Hookshot, Stand ps5-v0.1.0-beta.1):
  gpu/vk/vk_menu.h      struct Options: Werte und Standards
  gpu/vk/vk_menu.cpp    rows[]: Zeilen, Grenzen, Texte; ini_key(): Schluessel (Zeilenname klein, Leerzeichen -> _, mit
                        den Ausnahmen output_res, resolution, upscaling, dlss); menu_init(): fehlende Schluessel behalten
                        den Standard, Werte werden auf die Grenzen gekappt; options_version fehlt -> Game speed Real time
  host/nn_applet.c      language.txt: erste Zeile, die kein Kommentar ist, einer der 16 Codes
  host/hos_main.c       hookshot_env.txt: nur RX_/HOS_/HOOKSHOT_/... und keine Werte mit /
  readme.md, docs/development.md, docs/PS5.md
Die Datei wird nur gelesen, wenn das Spiel startet; Hookshot schreibt die ini selbst neu, wenn man im Insert-Menue etwas
aendert (Touchpad-Klick + Options auf dem DualSense oeffnet es, host/nn_hid.c + host/ps5/hos_sdl_ps5.c).
"""
import ftplib
import io
import os

TITLE = os.environ.get("PS5_TITLE_DIR", "/data/homebrew/PPSA99024").rstrip("/")

LANGUAGES = [("en-US", "Englisch (USA)"), ("en-GB", "Englisch (UK)"), ("fr", "Französisch (Frankreich)"),
             ("fr-CA", "Französisch (Kanada)"), ("de", "Deutsch"), ("it", "Italienisch"), ("es", "Spanisch (Spanien)"),
             ("es-419", "Spanisch (Lateinamerika)"), ("pt-BR", "Portugiesisch (Brasilien)"), ("nl", "Niederländisch"),
             ("pl", "Polnisch"), ("ru", "Russisch"), ("ja", "Japanisch"), ("ko", "Koreanisch"),
             ("zh-Hans", "Chinesisch (vereinfacht)"), ("zh-Hant", "Chinesisch (traditionell)")]
LANG_EN = ["English (US)", "English (UK)", "French (France)", "French (Canada)", "German", "Italian", "Spanish (Spain)",
           "Spanish (Latin America)", "Portuguese (Brazil)", "Dutch", "Polish", "Russian", "Japanese", "Korean",
           "Chinese (Simplified)", "Chinese (Traditional)"]

ONOFF = [(0, "Aus"), (1, "An")]

# Gruppe, Schluessel, Titel, Standard, Auswahl [(Wert, Text)], Erklaerung, Hinweis (PS5 / Neustart)
INI = [
    ("Grafik", "quality_preset", "Qualitätsvoreinstellung", 0,
     [(0, "Eigene (Custom)"), (1, "Minimum (4 GB)"), (2, "Niedrig (6 GB)"), (3, "Ausgewogen (8 GB)"), (4, "Hoch (12 GB)"),
      (5, "Ultra (16 GB+)")],
     "Setzt Renderauflösung, Skalierfilter, Schärfe, Zwischenbilder und Speichergrenzen für eine GPU mit so viel Speicher. "
     "Ändert man danach selbst eine dieser Zeilen, springt sie auf Eigene. Hier gesetzt wirken nur die Speichergrenzen der "
     "Voreinstellung: die einzelnen Zeilen setzt das Spiel erst, wenn sie im Insert-Menü gewählt wird.",
     "Auf der PS5 knapp: laut docs/PS5.md geht der Speicher unter Last nach einer Weile aus. Eigene ist der sichere Wert."),
    ("Grafik", "frame_generation", "Zwischenbilder (Frame Generation)", 0,
     [(0, "Aus"), (1, "Auto (bis zur Bildwiederholrate)"), (2, "2x"), (3, "3x"), (4, "4x"), (5, "5x"), (6, "6x"),
      (7, "7x"), (8, "8x")],
     "Berechnet Bilder zwischen den echten Spielbildern: flüssiger, aber etwas mehr Eingabeverzögerung und Artefakte bei "
     "schnellen Bewegungen oder Schnitten.",
     "PS5: 2x und 3x macht PS5_MihawkGen (im Build enthalten), darüber die eigene Interpolation des Renderers. Getestet: "
     "33-40 fps nativ im Kokiri-Wald, mit 2x doppelt so viele angezeigt."),
    ("Grafik", "frame_pacing", "Bildtaktung (Frame Pacing)", 0, ONOFF,
     "Aus: jedes Bild sofort zeigen. An: in gleichmäßigem Abstand, weniger Ruckeln, bis zu ein Bild mehr Verzögerung.", ""),
    ("Grafik", "output_res", "Ausgabeauflösung", 0,
     [(0, "2048x1152 (Spielstandard)"), (3, "1920x1080"), (1, "2560x1440"), (2, "3840x2160")],
     "Die Größe des ganzen Spielbilds samt HUD, bevor es auf den Bildschirm skaliert wird. Nur im Docked-Profil.",
     "Wirkt nach einem Neustart des Spiels. 3840x2160 bekommt einen größeren GPU-Speicherpool, kostet also Speicher, der "
     "auf der PS5 schon knapp ist."),
    ("Grafik", "dlss", "Upscaler", 0, [(0, "Spieleigener"), (3, "AMD FSR 3.1")],
     "Was das 3D-Bild auf die Ausgabeauflösung hochrechnet. FSR 3.1 ist in jedem Build enthalten und läuft auf GPUs mit "
     "Vulkan 1.3, Push-Deskriptoren und bestimmten Speicherformaten. DLSS/DLAA gibt es nur mit NVIDIA-Karten.",
     "Ob FSR 3.1 mit RADV auf der PS5 läuft: ungeprüft. Läuft es nicht, nimmt das Spiel den eigenen (im Log steht "
     "'vk: fsr3: ... can run on this GPU' oder nicht)."),
    ("Grafik", "resolution", "Renderauflösung", 0,
     [(0, "Auto (dynamisch, wie das Spiel)"), (1, "100 %"), (2, "75 %"), (3, "67 % (FSR: Quality)"),
      (5, "58 % (FSR: Balanced)"), (4, "50 % (FSR: Performance)"), (6, "33 % (FSR: Ultra Performance)")],
     "Anteil der Ausgabeauflösung, in dem das 3D gezeichnet wird; der Upscaler füllt den Rest. Auto nutzt die dynamische "
     "Auflösung des Spiels. Mit dem spieleigenen Upscaler gibt es 100/75/67/50 %, mit FSR 3.1 dessen Modi.",
     "Niedriger = mehr fps und weniger Speicher."),
    ("Grafik", "upscaling", "Skalierfilter zum Bildschirm", 0, [(0, "Aus (einfache Kopie)"), (1, "Catmull-Rom"), (2, "Lanczos")],
     "Wie das fertige Bild auf die Bildschirmgröße gebracht wird, wenn sie von der Ausgabeauflösung abweicht (z. B. "
     "2048x1152 auf einem 4K-Fernseher). Catmull-Rom schärfer, Lanczos noch schärfer, kann an Kanten überschwingen.", ""),
    ("Grafik", "sharpness", "Schärfe", 0, [(v, "%d %%" % v) for v in range(0, 101, 10)],
     "Schärft das Bild auf dem Weg zum Bildschirm. Zu viel zeigt Halos an Kanten.", ""),
    ("Grafik", "frame_rate_cap", "Bildratenbegrenzung", 0,
     [(0, "60 (wie die Konsole)"), (1, "90"), (2, "120"), (3, "144"), (4, "165"), (5, "240")],
     "Höchstens so viele Bilder pro Sekunde. Über 60 hält das Spiel die Echtzeit.",
     "Wirkt nach einem Neustart. Auf der PS5 kaum sinnvoll: laut docs/PS5.md 33-40 fps im Kokiri-Wald."),
    ("Grafik", "handheld_profile", "Handheld-Profil", 0, ONOFF,
     "Lässt das Spiel laufen, als wäre die Switch 2 nicht im Dock: niedrigere Auflösungen, weniger GPU-Last.",
     "Wirkt nach einem Neustart. Kann auf der PS5 bei Ruckeln oder Speichermangel helfen."),
    ("Grafik", "ultrawide", "Ultrawide", 0, [(0, "16:9"), (1, "Bildschirmform")],
     "Die Kamera nimmt die Form des Bildschirms an (breiter oder schmaler als 16:9). Das HUD bleibt gestreckt.",
     "Wirkt nach einem Neustart. Am 16:9-Fernseher ohne Wirkung."),
    ("Grafik", "robust_buffers", "Robuste Puffer", 0, [(0, "Auto (an)"), (1, "Aus"), (2, "An")],
     "Puffer-Lesezugriffe mit Grenzprüfung: ein Lesen über das Ende wird verworfen, statt die GPU anzuhalten.",
     "Wirkt nach einem Neustart. Aus kann schneller sein, riskiert aber GPU-Hänger."),
    ("Grafik", "descriptor_reuse", "Deskriptor-Wiederverwendung", 0, ONOFF,
     "Ein Draw behält seine Deskriptoren, solange sich seine Textur-Slots nicht ändern; Texture-Streaming baut dann nicht "
     "jedes Bild alle Sets neu.", "Wirkt nach einem Neustart. Experimentell."),
    ("Grafik", "sampler_cache", "Sampler-Cache", 0, ONOFF,
     "Sampler-Daten liegen beim Replay-Thread, ein Sampler braucht dann keine Sperre. Hilft beim Texture-Streaming.",
     "Wirkt nach einem Neustart. Experimentell."),
    ("Spiel", "fps_counter", "FPS-Anzeige", 0, ONOFF,
     "Bilder pro Sekunde oben rechts. Mit Zwischenbildern auch die echte Bildrate des Spiels.", ""),
    ("Spiel", "game_speed", "Spielgeschwindigkeit", 1, [(1, "Echtzeit"), (0, "Pro Bild")],
     "Wie das Spiel unter 60 fps die Zeit hält. Echtzeit: normale Geschwindigkeit bis 15 fps durch längere Schritte. Pro "
     "Bild: ein Schritt je Bild, das Spiel wird langsamer, wenn es unter 60 fps fällt.",
     "Auf der PS5 (33-40 fps) läuft das Spiel mit Pro Bild deutlich langsamer."),
    ("Spiel", "text_speed", "Textgeschwindigkeit", 0, [(0, "Normal"), (1, "2x"), (2, "4x"), (3, "Sofort")],
     "Wie schnell Dialogtext erscheint. Sofort: jede Seite auf einmal, wie mit A.", ""),
    ("Spiel", "audio_output", "Tonausgabe", 0, [(0, "Auto"), (1, "Stereo"), (2, "5.1")],
     "Für welche Lautsprecher das Spiel mischt. Auto: 5.1, wenn das Ausgabegerät 5.1 oder mehr hat.",
     "Wirkt nach einem Neustart. Auf der PS5 gibt sceAudioOut aus; ob 5.1 dort ankommt: ungeprüft."),
    ("Spiel", "debug_tools", "Debug-Werkzeuge", 0, ONOFF,
     "Testwerkzeuge im Debug-Tab: Flugmodus, freie Kamera, Teleport, Links Alter, Inventar, Uhr, Herzschutz.",
     "Auch per Schalter HOS_OOT_CHEATS=1 (unten)."),
    ("Steuerung", "layout_preset", "Tastenbelegung", 0,
     [(0, "Nintendo (A rechts, B unten)"), (1, "Xbox / PC (A unten, B rechts, X links, Y oben)"),
      (2, "Getauscht (A unten, B rechts, X/Y wie Switch)")],
     "Welche Gesichtstaste welche Switch-Taste ist. Auf dem DualSense: unten = Kreuz, rechts = Kreis.",
     "Eine eigene Belegung (Custom) nur im Insert-Menü; die pad_-Zeilen in der ini bleiben beim Speichern hier erhalten."),
    ("Steuerung", "button_prompts", "Tastensymbole", 0,
     [(0, "Auto (vom Controller)"), (1, "Switch"), (2, "Xbox"), (3, "PlayStation 4"), (4, "PlayStation 5"),
      (5, "Steam Deck")],
     "Welche Tastensymbole das Spiel in Texten und Menüs zeigt, passend zur Belegung.",
     "Auf der PS5 meldet sich der Controller als 'DualSense'; PlayStation 5 erzwingt die PS-Symbole."),
    ("Steuerung", "invert_camera_x", "Kamera X invertieren", 0, ONOFF, "Links/rechts am rechten Stick umkehren.", ""),
    ("Steuerung", "invert_camera_y", "Kamera Y invertieren", 0, ONOFF, "Oben/unten am rechten Stick umkehren.", ""),
    ("Steuerung", "stick_dead_zone", "Stick-Totzone", 0,
     [(0, "Standard (24 %)"), (1, "5 %"), (2, "10 %"), (3, "15 %"), (4, "20 %"), (5, "30 %")],
     "Wie weit ein Stick bewegt werden muss, bevor das Spiel es sieht. Niedriger für präzise Sticks, höher bei Drift.", ""),
    ("Steuerung", "rumble_strength", "Vibration", 100,
     [(0, "Aus"), (25, "25 %"), (50, "50 %"), (75, "75 %"), (100, "100 %"), (125, "125 %"), (150, "150 %")],
     "Stärke der Vibration in Prozent der Spielvorgabe.", ""),
]

# Schalter in hookshot_env.txt: Name, Titel, Standard (""=nicht gesetzt), Auswahl, Erklaerung, Hinweis
ENV = [
    ("HOS_OOT_CHEATS", "Debug-Menü (Cheats)", "", [("", "Aus"), ("1", "An")],
     "Schaltet das Debug-Menü frei: im Insert-Menü unter Gameplay → Cheats (Flug, freie Kamera, Teleport, Inventar ...).",
     "readme.md"),
    ("RX_VK_MIHAWKGEN", "PS5_MihawkGen für Zwischenbilder", "", [("", "An (Standard)"), ("0", "Aus")],
     "Bei 2x und 3x rechnet auf der PS5 das neuronale Netz von PS5_MihawkGen die Zwischenbilder. Aus: die eigene "
     "Interpolation des Renderers.", "docs/PS5.md"),
    ("RX_VK_FRAMEGEN", "Zwischenbilder erzwingen aus", "", [("", "wie im Menü"), ("0", "immer aus")],
     "0: keine Zwischenbilder, egal was im Menü steht.", "docs/development.md"),
    ("RX_VK_MOVIE_UPSCALE", "Upscaling der Videos", "", [("", "auto (Standard)"), ("linear", "linear")],
     "auto: neuronales Upscaling der Zwischensequenz-Videos, Rückfall auf linear, wenn ein Videobild die GPU über 40 ms "
     "kostet (nur NVIDIA nutzt die Netze, sonst immer linear). linear: immer das einfache, weicher.", "readme.md"),
    ("RX_VK_ASTC_RGBA8", "AMD-Texturfehler-Workaround", "", [("", "Aus"), ("1", "An")],
     "Behält ASTC-Texturen als RGBA8 statt sie neu nach BC3 zu kodieren. Gegen blockige oder dunkle Texturen auf "
     "AMD-GPUs (Upstream-Issues #57, #1006).",
     "Braucht deutlich mehr Grafikspeicher: auf der PS5 nur bei Texturfehlern, sonst droht Speichermangel."),
    ("HOOKSHOT_OCCLUSION_OFF", "Occlusion Queries aus", "", [("", "Aus"), ("1", "An")],
     "Keine Occlusion Queries (Fritchiis 'Occlusion Off', laut Quellkommentar in nx2/lift.py).",
     "Wirkung auf der PS5 ungeprüft."),
]
ENV_NAMES = {e[0] for e in ENV}


def connect():
    host = os.environ.get("PS5_HOST", "").strip()
    if not host or host == "0.0.0.0":
        raise RuntimeError("PS5_HOST ist nicht gesetzt")
    f = ftplib.FTP()
    f.connect(host, int(os.environ.get("PS5_FTP_PORT", "2121")), timeout=20)
    f.login()
    f.voidcmd("TYPE I")
    return f


def get_text(f, name):
    b = bytearray()
    try:
        f.retrbinary("RETR %s/%s" % (TITLE, name), b.extend)
    except ftplib.all_errors:
        return None
    return b.decode("utf-8", "replace")


def put_text(f, name, text):
    path = "%s/%s" % (TITLE, name)
    data = text.encode("utf-8")
    try:
        f.storbinary("STOR " + path, io.BytesIO(data))
    except ftplib.error_perm:
        # (vom Spiel angelegt und fuer ftpsrv schreibgeschuetzt: der Title-Ordner gehoert dem Deploy, loeschen geht)
        f.delete(path)
        f.storbinary("STOR " + path, io.BytesIO(data))
    try:
        f.sendcmd("CHMOD 666 " + path)   # (das Spiel schreibt die ini selbst neu, wenn man im Menue etwas aendert)
    except ftplib.all_errors:
        pass


def parse_ini(text):
    out = {}
    for line in (text or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def parse_language(text):
    codes = {c.lower(): c for c, _ in LANGUAGES}
    for line in (text or "").splitlines():
        s = line.strip().lstrip("﻿")
        if not s or s.startswith("#"):
            continue
        c = s.split()[0].lower()
        if c in codes:
            return codes[c]
    return None


def load():
    f = connect()
    try:
        ini_t, env_t, lang_t = get_text(f, "hookshot_options.ini"), get_text(f, "hookshot_env.txt"), get_text(f, "language.txt")
    finally:
        f.quit()
    ini = parse_ini(ini_t)
    env = parse_ini(env_t)
    values = {}
    for _, key, _, default, choices, _, _ in INI:
        try:
            values[key] = int(ini[key]) if key in ini else default
        except ValueError:
            values[key] = default
    for name, _, default, _, _, _ in ENV:
        values[name] = env.get(name, default)
    values["language"] = parse_language(lang_t) or "en-US"
    return {"values": values, "found": {"hookshot_options.ini": ini_t is not None, "hookshot_env.txt": env_t is not None,
                                        "language.txt": lang_t is not None}}


def catalog():
    return {
        "ini": [{"group": g, "key": k, "title": t, "default": d, "choices": c, "help": h, "note": n}
                for g, k, t, d, c, h, n in INI],
        "env": [{"key": k, "title": t, "default": d, "choices": c, "help": h, "note": n} for k, t, d, c, h, n in ENV],
        "languages": LANGUAGES,
    }


def save(values):
    f = connect()
    try:
        # ini: vorhandene Zeilen behalten (pad_/key_, microphone_device, unbekannte), die verwalteten ersetzen
        lines = (get_text(f, "hookshot_options.ini") or "").splitlines()
        managed = {k for _, k, *_ in INI}
        out, seen = [], set()
        for line in lines:
            k = line.split("=", 1)[0].strip() if "=" in line else None
            if k in managed:
                out.append("%s=%d" % (k, int(values.get(k))))
                seen.add(k)
            elif k == "options_version":
                continue
            elif line.strip():
                out.append(line)
        for _, k, _, default, *_ in INI:
            if k not in seen and int(values.get(k, default)) != default:
                out.append("%s=%d" % (k, int(values[k])))
        out.append("options_version=3")   # (ohne sie setzt das Spiel Game speed auf Echtzeit: menu_init)
        put_text(f, "hookshot_options.ini", "\n".join(out) + "\n")

        # env: fremde Zeilen behalten, die verwalteten neu
        env_lines = [l for l in (get_text(f, "hookshot_env.txt") or "").splitlines()
                     if l.strip() and l.split("=", 1)[0].strip() not in ENV_NAMES]
        for name, *_ in ENV:
            v = str(values.get(name, "")).strip()
            if v and "/" not in v and "\\" not in v:
                env_lines.append("%s=%s" % (name, v))
        put_text(f, "hookshot_env.txt", "\n".join(env_lines) + ("\n" if env_lines else ""))

        # language.txt im Format, das das Spiel selbst schreibt (host/nn_applet.c)
        code = values.get("language", "en-US")
        if code not in {c for c, _ in LANGUAGES}:
            code = "en-US"
        text = ("# The game's language. Change the line below to one of the codes listed here, save, and start the game "
                "again.\n\n%s\n\n" % code) + "".join("# %-8s %s\n" % (c, n) for (c, _), n in zip(LANGUAGES, LANG_EN))
        put_text(f, "language.txt", text)
    finally:
        f.quit()
    return load()
