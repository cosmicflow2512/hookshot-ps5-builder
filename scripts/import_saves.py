"""OoT-Spielstaende von PS5_Lichii (bzw. ProsperoEden) auf der PS5 nach Hookshot (PPSA99024) uebernehmen, per FTP.

    import_saves.py [--list] [--from <Ordner auf der PS5>] [--keep-settings]

Beide halten die Saves als dieselben Dateien (PS5_Hookshot docs/saves.md): account.sav, option.sav, slot_NN/. Lichii
liegt in Edens Pfad unter seinem Datenordner (/data/lichii bzw. vor v1.20.00 /data/prosperoeden):
user/nand/user/save/0000000000000000/<profil>/0400486024DEC000/ (neuere Eden-Staende auch .../account/<profil>/.../0/).
Hookshot auf der PS5: /data/homebrew/PPSA99024/user/save/<uid>/, uid 5a3c9e1f0b7d24680000000000000001 (host/nn_applet.c
user_uid, host/nn_fs.c MountSaveData).

Wie scripts/oot_saves.py: die slot_*-Ordner, account.sav und option.sav werden kopiert, die slot_*-Ordner des Ziels
vorher ersetzt. Das Ziel wird zuerst nach $CONFIG_DIR/save-backup/<zeit>/ gesichert. Hookshot darf dabei nicht laufen.
"""
import argparse
import ftplib
import io
import os
import sys
import time

GAME = "0400486024dec000"
ROOTS = ("/data/lichii/user", "/data/prosperoeden/user")
HOOKSHOT_SAVE = "/data/homebrew/PPSA99024/user/save/5a3c9e1f0b7d24680000000000000001"


def connect():
    host = os.environ.get("PS5_HOST", "").strip()
    if not host or host == "0.0.0.0":
        sys.exit("PS5_HOST ist nicht gesetzt")
    port = int(os.environ.get("PS5_FTP_PORT", "2121"))
    f = ftplib.FTP()
    try:
        f.connect(host, port, timeout=30)
    except OSError as e:
        sys.exit("keine FTP-Verbindung zu %s:%d (%s)" % (host, port, e))
    f.login()
    f.voidcmd("TYPE I")
    return f


def ls(f, path):
    """[(name, 'dir'|'file', modify)] eines Ordners; [] wenn es ihn nicht gibt"""
    out = []
    try:
        for name, facts in f.mlsd(path, facts=["type", "modify"]):
            t = facts.get("type", "").lower()
            if name in (".", "..") or t in ("cdir", "pdir"):
                continue
            out.append((name, "dir" if t == "dir" else "file", facts.get("modify", "")))
        return out
    except ftplib.error_perm:
        pass
    lines = []
    try:
        f.retrlines("LIST " + path, lines.append)
    except ftplib.all_errors:
        return []
    for l in lines:
        parts = l.split(None, 8)
        if len(parts) < 9 or parts[8] in (".", ".."):
            continue
        out.append((parts[8], "dir" if l.startswith("d") else "file", ""))
    return out


def is_save(entries):
    names = {n for n, t, _ in entries}
    return "account.sav" in names or any(n.startswith("slot_") and t == "dir" for n, t, _ in entries)


def find_saves(f):
    found = []

    def walk(path, depth):
        if depth > 9:
            return
        entries = ls(f, path)
        for name, t, _ in entries:
            if t != "dir":
                continue
            sub = path + "/" + name
            if name.lower() == GAME:
                for cand in (sub, sub + "/0"):
                    e = ls(f, cand)
                    if is_save(e):
                        newest = max((m for n, _, m in e if m), default="")
                        for n, t2, _ in e:
                            if t2 == "dir" and n.startswith("slot_"):
                                newest = max([newest] + [m for _, _, m in ls(f, cand + "/" + n) if m])
                        found.append((cand, e, newest))
            else:
                walk(sub, depth + 1)

    for root in ROOTS:
        walk(root, 0)
    return found


def fmt(modify):
    return "%s-%s-%s %s:%s" % (modify[0:4], modify[4:6], modify[6:8], modify[8:10], modify[10:12]) if len(modify) >= 12 else "?"


def get(f, path):
    b = bytearray()
    f.retrbinary("RETR " + path, b.extend)
    return bytes(b)


def mkdirs(f, path):
    cur = ""
    for part in path.strip("/").split("/"):
        parent, cur = cur or "/", cur + "/" + part
        try:
            f.mkd(cur)
        except ftplib.all_errors as e:
            if not any(n == part and t == "dir" for n, t, _ in ls(f, parent)):
                sys.exit("Ordner %s laesst sich auf der PS5 nicht anlegen: %s" % (cur, str(e).strip()))


def chmod(f, mode, path):
    try:
        f.sendcmd("CHMOD %s %s" % (mode, path))   # (ftpsrv: CHMOD <mode> <path>)
        return True
    except ftplib.all_errors:
        return False


def writable(f, path):
    probe = path + "/.import-probe"
    try:
        f.mkd(probe)
        f.rmd(probe)
        return True
    except ftplib.all_errors:
        return False


def make_target_writable(f):
    """Hookshot legt user/save/<uid> als Spielprozess an; ftpsrv darf darin dann nichts anlegen (550 Permission denied).
    Erst CHMOD versuchen, sonst user/ beiseite legen (PPSA99024/ hat das Deploy per FTP angelegt, dort darf ftpsrv
    umbenennen) und user/save/<uid> neu anlegen, offen fuer beide (777)."""
    global HOOKSHOT_SAVE
    title = HOOKSHOT_SAVE.rsplit("/", 3)[0]
    mkdirs(f, HOOKSHOT_SAVE)
    if writable(f, HOOKSHOT_SAVE):
        return
    for p in (title + "/user", title + "/user/save", HOOKSHOT_SAVE):
        chmod(f, "777", p)
    if writable(f, HOOKSHOT_SAVE):
        print("Rechte von Hookshots Save-Ordner per CHMOD geoeffnet", flush=True)
        return
    old = title + "/user.vor-import-" + time.strftime("%Y%m%d-%H%M%S")
    try:
        f.rename(title + "/user", old)
    except ftplib.all_errors as e:
        sys.exit("Hookshots Save-Ordner ist fuer ftpsrv schreibgeschuetzt und laesst sich nicht beiseite legen: %s" %
                 str(e).strip())
    print("Hookshots user/ war fuer ftpsrv schreibgeschuetzt: beiseite gelegt als %s, neu angelegt" % old, flush=True)
    mkdirs(f, HOOKSHOT_SAVE)
    for p in (title + "/user", title + "/user/save", HOOKSHOT_SAVE):
        chmod(f, "777", p)
    if not writable(f, HOOKSHOT_SAVE):
        sys.exit("%s ist auch neu angelegt nicht beschreibbar" % HOOKSHOT_SAVE)


def rmtree(f, path):
    for name, t, _ in ls(f, path):
        p = path + "/" + name
        if t == "dir":
            rmtree(f, p)
        else:
            f.delete(p)
    f.rmd(path)


def tree_files(f, path, rel=""):
    out = []
    for name, t, _ in ls(f, path):
        if t == "dir":
            out += tree_files(f, path + "/" + name, rel + name + "/")
        else:
            out.append(rel + name)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="nur anzeigen")
    ap.add_argument("--from", dest="src", default=os.environ.get("SAVE_FROM") or None, help="Lichii-Saveordner auf der PS5 (sonst der zuletzt gespeicherte)")
    ap.add_argument("--keep-settings", action="store_true", help="option.sav von Hookshot behalten")
    a = ap.parse_args()
    f = connect()

    print("Suche Lichii-Saves unter %s ..." % ", ".join(ROOTS), flush=True)
    found = find_saves(f)
    for path, e, newest in found:
        slots = sorted(n for n, t, _ in e if t == "dir" and n.startswith("slot_"))
        print("  %s\n    %s, zuletzt %s" % (path, ", ".join(slots) or "keine Slots", fmt(newest)), flush=True)
    global HOOKSHOT_SAVE
    base = HOOKSHOT_SAVE.rsplit("/", 1)[0]
    existing = [n for n, t, _ in ls(f, base) if t == "dir"]
    if len(existing) == 1:   # (der Ordner, den Hookshot selbst angelegt hat, falls seine uid anders lautet)
        HOOKSHOT_SAVE = base + "/" + existing[0]
    tgt = ls(f, HOOKSHOT_SAVE)
    print("Hookshot: %s\n    %s" % (HOOKSHOT_SAVE, ", ".join(sorted(n for n, t, _ in tgt if n.startswith("slot_")))
                                     or ("leer" if tgt else "noch kein Spielstand")), flush=True)
    if a.list:
        return
    if a.src:
        src = a.src.rstrip("/")
        e = ls(f, src)
        if not is_save(e):
            sys.exit("%s enthaelt keinen Spielstand" % src)
    else:
        if not found:
            sys.exit("keine Lichii-Saves von Ocarina of Time gefunden")
        src, e, _ = max(found, key=lambda x: x[2])
        if len(found) > 1:
            print("Mehrere gefunden, nehme den zuletzt gespeicherten (anderen mit SAVE_FROM waehlen).", flush=True)
    slots = sorted(n for n, t, _ in e if t == "dir" and n.startswith("slot_"))
    if not slots:
        sys.exit("%s hat keine slot_*-Ordner" % src)
    files = [n for n in ("account.sav", "option.sav") if any(n == x for x, t, _ in e if t == "file")]
    if a.keep_settings and "option.sav" in files:
        files.remove("option.sav")

    backup = os.path.join(os.environ.get("CONFIG_DIR", "/config"), "save-backup", time.strftime("%Y%m%d-%H%M%S"))
    old = tree_files(f, HOOKSHOT_SAVE) if tgt else []
    for rel in old:
        p = os.path.join(backup, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(get(f, HOOKSHOT_SAVE + "/" + rel))
    if old:
        print("Backup des Hookshot-Saves (%d Dateien): %s" % (len(old), backup), flush=True)

    make_target_writable(f)
    tgt = ls(f, HOOKSHOT_SAVE)
    for name, t, _ in tgt:
        if t == "dir" and name.startswith("slot_"):
            rmtree(f, HOOKSHOT_SAVE + "/" + name)
    n = 0
    for s in slots:
        for rel in tree_files(f, src + "/" + s):
            data = get(f, src + "/" + s + "/" + rel)
            d = os.path.dirname(HOOKSHOT_SAVE + "/" + s + "/" + rel)
            mkdirs(f, d)
            chmod(f, "777", d)
            f.storbinary("STOR " + HOOKSHOT_SAVE + "/" + s + "/" + rel, io.BytesIO(data))
            chmod(f, "666", HOOKSHOT_SAVE + "/" + s + "/" + rel)
            n += 1
    for name in files:
        f.storbinary("STOR " + HOOKSHOT_SAVE + "/" + name, io.BytesIO(get(f, src + "/" + name)))
        chmod(f, "666", HOOKSHOT_SAVE + "/" + name)
        n += 1
    f.quit()
    print("Uebernommen: %s (%s%s) -> %s, %d Dateien" % (src, ", ".join(slots), (", " + ", ".join(files)) if files else "",
                                                        HOOKSHOT_SAVE, n), flush=True)


if __name__ == "__main__":
    main()
