#!/usr/bin/env python3
"""Atalho da área de trabalho — dispara atualização remota segura (máx. 1x/dia)."""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

CONFIG_PATH = Path.home() / ".palpitaria" / "launcher.json"
TRIGGER_PATH = "/api/v1/pipeline/trigger"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"Config não encontrada: {CONFIG_PATH}")
        print("Execute: powershell -ExecutionPolicy Bypass -File scripts\\setup_desktop_launcher.ps1")
        input("Pressione Enter para fechar...")
        sys.exit(1)
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def sign_request(secret: str, timestamp: str) -> str:
    payload = f"{timestamp}\nPOST\n{TRIGGER_PATH}\n"
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def main() -> None:
    cfg = load_config()
    app_url = str(cfg.get("app_url", "")).rstrip("/")
    secret = str(cfg.get("secret", "")).strip()
    comp = str(cfg.get("comp", "WC")).strip() or "WC"

    if not app_url or not secret:
        print("launcher.json incompleto: defina app_url e secret.")
        input("Pressione Enter para fechar...")
        sys.exit(1)

    timestamp = str(int(time.time()))
    signature = sign_request(secret, timestamp)
    url = f"{app_url}{TRIGGER_PATH}?comp={comp}"

    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "X-Pipeline-Timestamp": timestamp,
            "X-Pipeline-Signature": signature,
            "Content-Type": "application/json",
            "User-Agent": "PalpitariaDesktopLauncher/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw).get("detail", raw)
        except json.JSONDecodeError:
            detail = raw or exc.reason
        print(f"Erro {exc.code}: {detail}")
        if exc.code == 429:
            print("\nRegra de segurança: só 1 atualização remota por dia.")
        input("Pressione Enter para fechar...")
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"Sem conexão com o servidor: {exc.reason}")
        input("Pressione Enter para fechar...")
        sys.exit(1)

    watch_url = body.get("watch_url")
    if not watch_url:
        print("Resposta inválida do servidor (sem watch_url).")
        input("Pressione Enter para fechar...")
        sys.exit(1)

    print("Atualização iniciada no servidor.")
    print(f"Dia: {body.get('run_day', '—')} · Comp: {body.get('comp', 'WC')}")
    webbrowser.open(watch_url)
    time.sleep(2)


if __name__ == "__main__":
    main()
