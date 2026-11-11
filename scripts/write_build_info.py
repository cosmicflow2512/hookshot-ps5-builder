"""Nach einem Build festhalten, was gebaut wurde: write_build_info.py <PS5_Hookshot> <build-info.json>"""
import json
import re
import subprocess
import sys
import time

hs, out = sys.argv[1], sys.argv[2]


def g(*a):
    return subprocess.run(["git", "-C", hs] + list(a), capture_output=True, text=True).stdout.strip()


text = open(hs + "/ps5/build-title.sh").read()
pins = {k: (re.search(r"^%s=([0-9a-f]{40})" % k, text, re.M) or [None, None])[1]
        for k in ("VULKAN_REV", "MESA_REV", "SDK_REV", "MIHAWKGEN_REV")}
with open(out, "w") as fh:
    json.dump({"describe": g("describe", "--tags", "--always"), "commit": g("rev-parse", "HEAD"), "pins": pins,
               "date": time.strftime("%d.%m.%Y %H:%M")}, fh, indent=1)
