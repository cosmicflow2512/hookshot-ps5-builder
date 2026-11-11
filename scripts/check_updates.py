"""Auf Updates pruefen: was gebaut und auf die PS5 kopiert ist, gegen den Stand auf GitHub.

  - PS5_Hookshot: neuestes ps5-v*-Release und main (git ls-remote), gegen den gebauten Stand ($CONFIG_DIR/build-info.json,
    vom Build geschrieben)
  - die Pins (PS5_Vulkan, PS5_Mesa, PS5_PayloadSDK, PS5_MihawkGen) aus ps5/build-title.sh des neuesten Release, gegen die
    gebauten
  - dieser Container: cosmicflow2512/hookshot-ps5-builder main gegen IMAGE_REV
  - die PS5: der zuletzt kopierte Build ($CONFIG_DIR/deploy-manifest.json) gegen dist/PPSA99024
Ergebnis auch als $CONFIG_DIR/update-check.json fuer die Web-UI.
"""
import hashlib
import json
import os
import re
import subprocess
import time

CONFIG = os.environ.get("CONFIG_DIR", "/config")
HS = os.path.join(CONFIG, "src", "PS5_Hookshot")
GH = "https://github.com/mihawk-99"
PINS = ("VULKAN_REV", "MESA_REV", "SDK_REV", "MIHAWKGEN_REV")
PIN_NAMES = {"VULKAN_REV": "PS5_Vulkan", "MESA_REV": "PS5_Mesa (RADV)", "SDK_REV": "PS5_PayloadSDK",
             "MIHAWKGEN_REV": "PS5_MihawkGen"}


def git(*a, cwd=None):
    r = subprocess.run(["git"] + list(a), cwd=cwd, capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "git " + " ".join(a))
    return r.stdout.strip()


def ls_remote(url, *refs):
    out = {}
    for line in git("ls-remote", url, *refs).splitlines():
        sha, ref = line.split("\t")
        out[ref] = sha
    return out


def vkey(tag):
    return [int(x) if x.isdigit() else x for x in re.split(r"[.\-]", tag.replace("ps5-v", ""))]


def pins_of(ref):
    text = git("show", "%s:ps5/build-title.sh" % ref, cwd=HS)
    return {k: (re.search(r"^%s=([0-9a-f]{40})" % k, text, re.M) or [None, None])[1] for k in PINS}


def sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    res = {"time": time.strftime("%d.%m.%Y %H:%M"), "lines": [], "update": False}
    say = lambda s: (res["lines"].append(s), print(s, flush=True))  # noqa: E731

    try:
        built = json.load(open(os.path.join(CONFIG, "build-info.json")))
    except (OSError, ValueError):
        built = None
    eboot = os.path.join(HS, "dist", "PPSA99024", "eboot.bin")
    head = os.path.join(HS, ".git", "HEAD")
    if not built and os.path.exists(eboot) and os.path.exists(head) and os.path.getmtime(eboot) > os.path.getmtime(head):
        # (Build von vor build-info.json: nach dem letzten Checkout gebaut, also vermutlich aus ihm)
        try:
            built = {"describe": git("describe", "--tags", "--always", cwd=HS) + " (vermutlich)",
                     "commit": git("rev-parse", "HEAD", cwd=HS), "pins": pins_of("HEAD"),
                     "date": time.strftime("%d.%m.%Y %H:%M", time.localtime(os.path.getmtime(eboot)))}
        except RuntimeError:
            built = None

    # PS5_Hookshot auf GitHub
    refs = ls_remote(GH + "/PS5_Hookshot.git", "refs/tags/ps5-v*", "refs/heads/main")
    tags = {}
    for ref, sha in refs.items():
        if ref.startswith("refs/tags/"):
            name = ref[len("refs/tags/"):]
            if name.endswith("^{}"):
                tags[name[:-3]] = sha          # (der Commit hinter einem annotierten Tag)
            else:
                tags.setdefault(name, sha)
    latest = max(tags, key=vkey) if tags else None
    main_sha = refs.get("refs/heads/main", "")
    say("PS5_Hookshot auf GitHub: neuestes Release %s (%s), main %s" % (latest, (tags.get(latest) or "")[:7], main_sha[:7]))
    if os.path.isdir(os.path.join(HS, ".git")):
        try:
            git("fetch", "-q", "--force", "--tags", "origin", cwd=HS)
            ahead = git("rev-list", "--count", "%s..origin/main" % latest, cwd=HS)
            say("  main ist %s Commits weiter als %s (Entwicklungsstand, HOOKSHOT_REF=main)" % (ahead, latest))
        except RuntimeError:
            pass

    ref_mode = os.environ.get("HOOKSHOT_REF", "latest")
    want = latest if ref_mode == "latest" else ("origin/main" if ref_mode == "main" else ref_mode)
    if not built:
        say("Gebaut: unbekannt (Build von vor dieser Pruefung). Nach dem naechsten Build steht hier der Stand.")
        res["update"] = True
    else:
        say("Gebaut: %s (%s) am %s" % (built.get("describe"), built.get("commit", "")[:7], built.get("date")))
        target_sha = tags.get(latest) if ref_mode == "latest" else (main_sha if ref_mode == "main" else None)
        if target_sha and not built.get("commit", "").startswith(target_sha[:12]):
            say("  NEU: %s ist verfuegbar -> Alles bauen" % (latest if ref_mode == "latest" else "main " + main_sha[:7]))
            res["update"] = True
        else:
            say("  aktuell (%s)" % ("neuestes Release" if ref_mode == "latest" else ref_mode))
        if latest and ref_mode == "latest":
            try:
                new = pins_of(latest)
                changed = [k for k in PINS if new.get(k) and built.get("pins", {}).get(k) != new[k]]
                for k in changed:
                    say("  %s: %s -> %s%s" % (PIN_NAMES[k], (built.get("pins", {}).get(k) or "?")[:7], new[k][:7],
                                             " (RADV wird neu gebaut)" if k == "MESA_REV" else ""))
            except RuntimeError:
                pass
    res["latest"], res["built"] = latest, built and built.get("describe")

    # dieser Container
    try:
        mine = ls_remote("https://github.com/cosmicflow2512/hookshot-ps5-builder.git", "refs/heads/main").get(
            "refs/heads/main", "")
        img = os.environ.get("IMAGE_REV", "")
        if img and mine and not mine.startswith(img[:12]):
            say("Container: Image %s, auf GitHub %s -> force update in Unraid" % (img[:7], mine[:7]))
            res["update"] = True
        else:
            say("Container: aktuell (%s)" % img[:7])
    except RuntimeError as e:
        say("Container: nicht pruefbar (%s)" % e)

    # PS5
    try:
        manifest = json.load(open(os.path.join(CONFIG, "deploy-manifest.json")))
    except (OSError, ValueError):
        manifest = {}
    host = os.environ.get("PS5_HOST", "")
    sent = next((v for k, v in manifest.items() if k.startswith(host + ":")), {})
    if not os.path.exists(eboot):
        say("PS5: kein Build vorhanden")
    elif not sent:
        say("PS5: noch nie von hier kopiert")
        res["update"] = True
    elif sent.get("eboot.bin") == sha1(eboot):
        say("PS5: hat den aktuellen Build")
    else:
        say("PS5: aelterer Build als in dist -> Auf die PS5 kopieren")
        res["update"] = True

    say("Ergebnis: %s" % ("es gibt etwas zu tun (siehe oben)" if res["update"] else "alles aktuell"))
    with open(os.path.join(CONFIG, "update-check.json"), "w") as fh:
        json.dump(res, fh, indent=1)


if __name__ == "__main__":
    main()
