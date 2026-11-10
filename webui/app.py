"""Web-UI fuer hookshot-ps5-builder: Stufen starten, Log mitlesen, Stand anzeigen. Nur Python-Standardbibliothek."""
import glob
import http.server
import json
import os
import signal
import subprocess
import threading
import time
import urllib.parse

CONFIG = os.environ.get("CONFIG_DIR", "/config")
LOGS = os.path.join(CONFIG, "logs")
HS = os.path.join(CONFIG, "src", "PS5_Hookshot")
PORT = int(os.environ.get("WEBUI_PORT", "8484"))
STAGES = ("all", "update", "build", "deploy")
HERE = os.path.dirname(os.path.abspath(__file__))

state = {"proc": None, "stage": None, "started": None, "ended": None, "code": None, "log": None}
lock = threading.Lock()


def start(stage):
    with lock:
        if state["proc"] and state["proc"].poll() is None:
            return False, "es laeuft schon: " + state["stage"]
        os.makedirs(LOGS, exist_ok=True)
        path = os.path.join(LOGS, time.strftime("%Y%m%d-%H%M%S") + "-" + stage + ".log")
        fh = open(path, "wb")
        proc = subprocess.Popen(["bash", "/app/scripts/build.sh", stage], stdout=fh, stderr=subprocess.STDOUT,
                                start_new_session=True)
        state.update(proc=proc, stage=stage, started=time.time(), ended=None, code=None, log=path)
        latest = os.path.join(LOGS, "latest.log")
        try:
            if os.path.lexists(latest):
                os.remove(latest)
            os.symlink(os.path.basename(path), latest)
        except OSError:
            pass

        def wait():
            code = proc.wait()
            fh.close()
            with lock:
                state.update(code=code, ended=time.time())
        threading.Thread(target=wait, daemon=True).start()
        return True, path


def stop():
    with lock:
        p = state["proc"]
        if p and p.poll() is None:
            os.killpg(p.pid, signal.SIGTERM)
            return True
    return False


def git_rev(name):
    d = os.path.join(CONFIG, "src", name)
    if not os.path.isdir(os.path.join(d, ".git")):
        return None
    r = subprocess.run(["git", "-C", d, "log", "-1", "--format=%h %ad %s", "--date=short"],
                       capture_output=True, text=True)
    t = subprocess.run(["git", "-C", d, "describe", "--tags", "--exact-match"], capture_output=True, text=True).stdout.strip()
    return ((t + " ") if t else "") + r.stdout.strip()[:90] or None


def status():
    with lock:
        p = state["proc"]
        running = bool(p and p.poll() is None)
        s = {"running": running, "stage": state["stage"], "started": state["started"], "ended": state["ended"],
             "code": state["code"], "log": state["log"]}
    nup_dir = os.environ.get("NUP_DIR", "/nup")
    s["nup"] = os.environ.get("NUP_FILE") or next(iter(sorted(glob.glob(os.path.join(nup_dir, "*.nup")) +
                                                             glob.glob(os.path.join(nup_dir, "*", "*.nup")))), None)
    s["ps5_host"] = os.environ.get("PS5_HOST", "")
    eboot = os.path.join(HS, "dist", "PPSA99024", "eboot.bin")
    s["build"] = time.strftime("%d.%m.%Y %H:%M", time.localtime(os.path.getmtime(eboot))) if os.path.exists(eboot) else None
    s["repos"] = {n: git_rev(n) for n in ("PS5_Hookshot", "PS5_Vulkan", "PS5_PayloadSDK", "PS5_MihawkGen", "PS5_Mesa")}
    st = os.statvfs(CONFIG)
    s["free_gb"] = round(st.f_bavail * st.f_frsize / (1 << 30), 1)
    return s


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/":
            with open(os.path.join(HERE, "index.html"), "rb") as fh:
                return self.send(200, fh.read(), "text/html; charset=utf-8")
        if u.path == "/api/status":
            return self.send(200, json.dumps(status()))
        if u.path == "/api/log":
            q = urllib.parse.parse_qs(u.query)
            off = int(q.get("from", ["0"])[0])
            path = state["log"] or os.path.join(LOGS, "latest.log")
            try:
                with open(path, "rb") as fh:
                    size = os.fstat(fh.fileno()).st_size
                    if off > size or off < 0:
                        off = 0
                    if off == 0 and size > 400_000:
                        off = size - 400_000
                    fh.seek(off)
                    chunk = fh.read(2_000_000)
            except OSError:
                return self.send(200, json.dumps({"next": 0, "text": ""}))
            return self.send(200, json.dumps({"next": off + len(chunk), "text": chunk.decode("utf-8", "replace")}))
        self.send(404, '{"error":"not found"}')

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/run":
            stage = urllib.parse.parse_qs(u.query).get("stage", [""])[0]
            if stage not in STAGES:
                return self.send(400, json.dumps({"ok": False, "msg": "unbekannte Stufe"}))
            ok, msg = start(stage)
            return self.send(200 if ok else 409, json.dumps({"ok": ok, "msg": msg}))
        if u.path == "/api/stop":
            return self.send(200, json.dumps({"ok": stop()}))
        self.send(404, '{"error":"not found"}')


if __name__ == "__main__":
    if os.environ.get("RUN_ON_START", "false") == "true":
        start("all")
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print("Web-UI auf Port %d" % PORT, flush=True)
    srv.serve_forever()
