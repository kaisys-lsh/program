#cry_cpi.py
import http.client
import urllib.parse
import json
import re
import time

from PyQt5.QtCore import QThread, pyqtSignal

from config.config import (
    CRY_USER, CRY_PW,
)
# IP/PORT/HTTPS 여부는 스레드 생성 시 인자로 받음

# ─────────────────────────────────────────
# CRY API 순수 함수
# ─────────────────────────────────────────
def cry_login_stdlib(ip: str, port: int, user: str, password: str,
                     timeout_sec: int = 5, use_https: bool = False):
    conn_cls = http.client.HTTPSConnection if use_https else http.client.HTTPConnection
    conn = conn_cls(ip, port, timeout=timeout_sec)
    try:
        path = "/api/register/v1/login"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        body = urllib.parse.urlencode({"user": user, "password": password})
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        response_text = resp.read().decode("utf-8", errors="replace")

        if resp.status < 200 or resp.status >= 300:
            return False, "", response_text, f"HTTP {resp.status} {resp.reason}"

        cookie_value = ""
        try:
            payload = json.loads(response_text)
            if isinstance(payload, dict) and "cookie" in payload:
                cookie_value = str(payload.get("cookie", ""))
        except json.JSONDecodeError:
            key = '"cookie"'
            idx = response_text.find(key)
            if idx >= 0:
                colon = response_text.find(":", idx)
                q1 = response_text.find('"', colon + 1) + 1
                q2 = response_text.find('"', q1)
                if colon != -1 and q1 != 0 and q2 != -1:
                    cookie_value = response_text[q1:q2]

        return bool(cookie_value), cookie_value, response_text, ""
    except Exception as e:
        return False, "", "", f"Send/Recv Error: {e}"
    finally:
        try:
            conn.close()
        except Exception:
            pass

def GetCloudDbSPL(cookie, ip: str, port: str,
                  timeout_sec: int = 5, use_https: bool = False) -> str:
    conn_cls = http.client.HTTPSConnection if use_https else http.client.HTTPConnection
    try:
        conn = conn_cls(ip, int(port), timeout=timeout_sec)
        path = "/api/screen/v1/dbSpl"
        headers = {"CRYCookie": cookie}
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
        if 200 <= resp.status < 300:
            return body
        else:
            return ""
    except Exception:
        return ""
    finally:
        try:
            conn.close()
        except Exception:
            pass

def extract_single_db(text: str):
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "data" in obj and isinstance(obj["data"], list) and obj["data"]:
            last = obj["data"][-1]
            if isinstance(last, dict) and "max" in last:
                try:
                    return float(last["max"])
                except Exception:
                    pass

        keys = {"db", "dba", "spl", "value", "val", "max", "level", "lv"}

        def dfs(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    if str(k).lower() in keys:
                        try:
                            return float(v)
                        except Exception:
                            pass
                for v in x.values():
                    r = dfs(v)
                    if r is not None:
                        return r
            elif isinstance(x, list):
                for it in reversed(x):
                    r = dfs(it)
                    if r is not None:
                        return r
            return None

        v = dfs(obj)
        if v is not None:
            return v
    except Exception:
        pass

    nums = re.findall(r"-?\d+(?:\.\d+)?", text)
    if nums:
        try:
            return float(nums[-1])
        except Exception:
            return None

    return None

# ─────────────────────────────────────────
# CRY API 스레드
# ─────────────────────────────────────────
class CryApiThread(QThread):
    db_ready = pyqtSignal(float)
    text_ready = pyqtSignal(str)

    def __init__(self, ip, port, user, pw,
                 use_https=False, interval_sec=1, timeout_sec=5,
                 parent=None):
        super().__init__(parent)
        self.ip = ip
        self.port = int(port)
        self.user = user
        self.pw = pw
        self.use_https = use_https
        self.interval_sec = max(1, int(interval_sec))
        self.timeout_sec = timeout_sec
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        def do_login():
            ok, cookie, resp_text, err = cry_login_stdlib(
                self.ip, self.port, self.user, self.pw,
                timeout_sec=self.timeout_sec, use_https=self.use_https
            )
            return ok, cookie, resp_text, err

        ok, cookie, resp_text, err = do_login()
        if not self._running:
            return
        if not ok:
            self.text_ready.emit(f"[LOGIN FAIL] {self.ip}:{self.port} | {err} | {resp_text}")
            return

        self.text_ready.emit(f"[LOGIN OK] {self.ip}:{self.port}")
        fail_streak = 0

        while self._running:
            text = GetCloudDbSPL(cookie, self.ip, str(self.port),
                                 timeout_sec=self.timeout_sec,
                                 use_https=self.use_https)
            if not self._running:
                break

            if text:
                fail_streak = 0
                self.text_ready.emit(text)
                v = extract_single_db(text)
                if v is not None:
                    try:
                        self.db_ready.emit(float(v))
                    except Exception as e:
                        self.text_ready.emit(f"[EMIT ERR] {e}")
            else:
                fail_streak += 1
                self.text_ready.emit(f"[EMPTY or ERR] fail_streak={fail_streak}")
                if fail_streak >= 3:
                    self.text_ready.emit("[RELOGIN] trying...")
                    ok, cookie, resp_text, err = do_login()
                    if ok:
                        self.text_ready.emit("[RELOGIN OK]")
                        fail_streak = 0
                    else:
                        self.text_ready.emit(f"[RELOGIN FAIL] {err} | {resp_text}")

            for _ in range(self.interval_sec * 10):
                if not self._running:
                    break
                time.sleep(0.1)
