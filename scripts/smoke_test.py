import sys
import http.client
import json
import time

HOST, PORT = "127.0.0.1", 8001


def req(method, path, body=None, cookie=None):
    conn = http.client.HTTPConnection(HOST, PORT)
    headers = {}
    data = None
    if body is not None:
        data = "&".join(f"{k}={v}" for k, v in body.items())
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if cookie:
        headers["Cookie"] = cookie
    conn.request(method, path, body=data, headers=headers)
    r = conn.getresponse()
    text = r.read().decode("utf-8", errors="replace")
    set_cookie = r.getheader("Set-Cookie")
    conn.close()
    return r.status, r.getheader("Location"), text, set_cookie


def main():
    print("=== GET / (no auth) ===")
    s, loc, t, sc = req("GET", "/")
    print(f"  status={s} location={loc}")
    assert s == 303 and loc == "/setup", "expected redirect to /setup"

    print("=== GET /setup ===")
    s, loc, t, sc = req("GET", "/setup")
    print(f"  status={s} contains 'Primo avvio': {'Primo avvio' in t}")
    assert s == 200 and "Primo avvio" in t

    print("=== POST /setup (create gabry) ===")
    s, loc, t, sc = req("POST", "/setup", {"username": "gabry", "password": "test12345", "password2": "test12345"})
    print(f"  status={s} location={loc} cookie={'yes' if sc else 'no'}")
    assert s == 303 and loc == "/" and sc
    cookie = sc.split(";")[0]
    print(f"  cookie={cookie[:40]}...")

    print("=== POST /setup again (should redirect to /login, already exists) ===")
    s, loc, t, sc = req("POST", "/setup", {"username": "x", "password": "y", "password2": "y"})
    print(f"  status={s} location={loc}")
    assert s == 303 and loc == "/login"

    print("=== GET / (with cookie) ===")
    s, loc, t, sc = req("GET", "/", cookie=cookie)
    print(f"  status={s} contains 'Ciao gabry': {'Ciao gabry' in t} len={len(t)}")
    assert s == 200 and "Ciao gabry" in t

    print("=== GET /stats ===")
    s, loc, t, sc = req("GET", "/stats", cookie=cookie)
    print(f"  status={s} contains 'Statistiche': {'Statistiche' in t}")
    assert s == 200

    print("=== GET /review ===")
    s, loc, t, sc = req("GET", "/review", cookie=cookie)
    print(f"  status={s} contains 'Ripasso': {'Ripasso' in t}")
    assert s == 200

    print("=== GET /quiz/start?mode=mixed (no questions yet) ===")
    s, loc, t, sc = req("GET", "/quiz/start?mode=mixed", cookie=cookie)
    print(f"  status={s} location={loc}")
    # no questions -> redirect to /review?empty=1
    assert s in (303, 200)

    print("\nALL HTTP SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())