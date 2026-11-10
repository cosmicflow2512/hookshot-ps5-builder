"""dist/PPSA99024 per FTP auf die PS5 (ftpsrv, Standardport 2121) und optional die .nup dazu.

    deploy.py --dist <dist/PPSA99024> [--upload-nup <spiel.nup>]

Umgebung: PS5_HOST, PS5_FTP_PORT (2121), PS5_TITLE_DIR (/data/homebrew/PPSA99024),
PS5_NUP_PATH (/data/prosperoeden/roms/oot/oot.nup): Ziel fuer UPLOAD_NUP.

Hookshot liest die romfs aus der .nup an festen Orten: ps5-v0.1.0-beta.1 nur /data/prosperoeden/roms/oot/oot.nup, neuere
Staende zuerst /data/lichii/roms/oot/oot.nup (host/ps5/win32_ps5.c hos_ps5_nup). HOS_PS5_NUP in hookshot_env.txt wirkt
nicht: die Datei nimmt keine Werte mit "/" an (host/hos_main.c env_line_allowed).

Hochgeladen wird nur, was sich seit dem letzten Deploy auf denselben Host geaendert hat (SHA-1 je Datei in
$CONFIG_DIR/deploy-manifest.json). Geloescht wird auf der Konsole nichts: user/ (Spielstaende), hookshot_options.ini
und der Shader-Cache bleiben. Weicht PS5_NUP_PATH vom Standard ab, wird HOS_PS5_NUP in hookshot_env.txt gesetzt
(andere Zeilen dort bleiben stehen).
"""
import argparse
import ftplib
import hashlib
import io
import json
import os
import sys
import time

DEFAULT_NUP = "/data/prosperoeden/roms/oot/oot.nup"
KNOWN_NUPS = ("/data/lichii/roms/oot/oot.nup", DEFAULT_NUP)


def connect(host, port):
    f = ftplib.FTP()
    f.connect(host, port, timeout=60)
    f.login()
    f.voidcmd("TYPE I")
    return f


def mkdirs(f, path):
    cur = ""
    for part in path.strip("/").split("/"):
        cur += "/" + part
        try:
            f.mkd(cur)
        except ftplib.all_errors:
            pass


def remote_size(f, path):
    try:
        return f.size(path)
    except ftplib.all_errors:
        return None


def sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def progress(done, total, t0, name):
    secs = max(time.time() - t0, 0.001)
    mib_s = done / secs / (1 << 20)
    pct = 100.0 * done / total if total else 100.0
    print("  %s: %5.1f%%  %8.1f / %.1f MiB  %.1f MiB/s" % (name, pct, done / (1 << 20), total / (1 << 20), mib_s),
          flush=True)


def put_file(f, local, remote, offset=0):
    total = os.path.getsize(local)
    sent = [offset]
    t0 = time.time()
    last = [t0]

    def cb(block):
        sent[0] += len(block)
        if time.time() - last[0] > 10:
            last[0] = time.time()
            progress(sent[0] - offset, total - offset, t0, os.path.basename(local))

    with open(local, "rb") as fh:
        if offset:
            fh.seek(offset)
            f.storbinary("STOR " + remote, fh, blocksize=1 << 20, callback=cb, rest=offset)
        else:
            f.storbinary("STOR " + remote, fh, blocksize=1 << 20, callback=cb)
    if total > (64 << 20):
        progress(sent[0] - offset, total - offset, t0, os.path.basename(local))


def set_env_line(f, title_dir, key, value):
    path = title_dir + "/hookshot_env.txt"
    buf = bytearray()
    try:
        f.retrbinary("RETR " + path, buf.extend)
    except ftplib.all_errors:
        pass
    lines = [l for l in buf.decode("utf-8", "replace").splitlines() if l.strip() and not l.startswith(key + "=")]
    if value:
        lines.append("%s=%s" % (key, value))
    f.storbinary("STOR " + path, io.BytesIO(("\n".join(lines) + "\n").encode()))
    print("  hookshot_env.txt: %s=%s" % (key, value or "(entfernt)"), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", required=True)
    ap.add_argument("--upload-nup")
    a = ap.parse_args()

    host = os.environ.get("PS5_HOST", "").strip()
    if not host or host == "0.0.0.0":
        sys.exit("PS5_HOST ist nicht gesetzt (IP der PS5)")
    port = int(os.environ.get("PS5_FTP_PORT", "2121"))
    title_dir = os.environ.get("PS5_TITLE_DIR", "/data/homebrew/PPSA99024").rstrip("/")
    nup_path = os.environ.get("PS5_NUP_PATH", DEFAULT_NUP).strip() or DEFAULT_NUP
    manifest_path = os.path.join(os.environ.get("CONFIG_DIR", "/config"), "deploy-manifest.json")

    try:
        manifest = json.load(open(manifest_path))
    except (OSError, ValueError):
        manifest = {}
    key = "%s:%d%s" % (host, port, title_dir)
    sent_before = {} if os.environ.get("FORCE_DEPLOY", "false") == "true" else manifest.get(key, {})

    try:
        f = connect(host, port)
    except OSError as e:
        sys.exit("keine FTP-Verbindung zu %s:%d (%s). Laeuft ftpsrv bzw. etaHENs FTP auf der PS5?" % (host, port, e))
    print("  verbunden mit %s:%d" % (host, port), flush=True)

    files = []
    for base, _, names in os.walk(a.dist):
        for n in sorted(names):
            files.append(os.path.join(base, n))
    uploaded = 0
    now = {}
    for local in files:
        rel = os.path.relpath(local, a.dist).replace(os.sep, "/")
        digest = sha1(local)
        now[rel] = digest
        remote = title_dir + "/" + rel
        if sent_before.get(rel) == digest and remote_size(f, remote) in (None, os.path.getsize(local)):
            continue
        mkdirs(f, os.path.dirname(remote))
        print("  %s (%.1f MiB)" % (rel, os.path.getsize(local) / (1 << 20)), flush=True)
        put_file(f, local, remote)
        uploaded += 1
        sent_before[rel] = digest
        manifest[key] = sent_before
        with open(manifest_path, "w") as fh:
            json.dump(manifest, fh, indent=1)
    print("  %d von %d Dateien hochgeladen, Rest unveraendert" % (uploaded, len(files)), flush=True)

    set_env_line(f, title_dir, "HOS_PS5_NUP", "")   # (frueher gesetzt, wirkt nicht: aufraeumen)

    if a.upload_nup:
        size = os.path.getsize(a.upload_nup)
        have = remote_size(f, nup_path)
        if have == size:
            print("  .nup liegt schon vollstaendig auf der PS5: %s" % nup_path, flush=True)
        else:
            mkdirs(f, os.path.dirname(nup_path))
            offset = have if have and have < size else 0
            print("  .nup -> %s (%.1f GiB%s)" % (nup_path, size / (1 << 30),
                                                ", fortgesetzt ab %.1f GiB" % (offset / (1 << 30)) if offset else ""),
                  flush=True)
            try:
                put_file(f, a.upload_nup, nup_path, offset)
            except ftplib.error_perm:
                if not offset:
                    raise
                print("  Fortsetzen nicht unterstuetzt, neu ab 0", flush=True)
                f = connect(host, port)
                put_file(f, a.upload_nup, nup_path, 0)
            if remote_size(f, nup_path) not in (None, size):
                sys.exit("  .nup auf der PS5 hat nicht die erwartete Groesse")
    found = [p for p in KNOWN_NUPS if remote_size(f, p)]
    if found:
        print("  .nup fuer Hookshot: %s%s" % (found[0], "" if DEFAULT_NUP in found else
              " (liest erst der Stand nach ps5-v0.1.0-beta.1; das Release sucht nur %s)" % DEFAULT_NUP), flush=True)
    else:
        print("  ACHTUNG: keine .nup unter %s. Ohne sie stuerzt Hookshot beim Start ab (SIGSEGV).\n"
              "  Eine vorhandene .nup verschieben (Lichii findet sie dort weiter, jeder Name unter roms/ geht):\n"
              "    curl -Q 'MKD /data/prosperoeden/roms/oot' -Q 'RNFR <alter Pfad>' -Q 'RNTO %s' ftp://%s:%d/\n"
              "  oder UPLOAD_NUP=true setzen." % (" bzw. ".join(KNOWN_NUPS), DEFAULT_NUP, host, port), flush=True)
    f.quit()
    print("  Deploy fertig. Start ueber ShadowMountPlus (%s)." % title_dir, flush=True)


if __name__ == "__main__":
    main()
