"""Utility to obtain Itaú sandbox OAuth tokens programatically."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict

import requests

SANDBOX_TOKEN_URL = "https://sandbox.devportal.itau.com.br/api/oauth/jwt"


def request_token(client_id: str, client_secret: str) -> Dict[str, Any]:
    """Request a sandbox token using the client credentials grant."""

    response = requests.post(
        SANDBOX_TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Falha ao obter token (status {response.status_code}): {response.text}"
        )
    return response.json()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Gera um token de sandbox do Itaú usando client_id e client_secret."
        )
    )
    parser.add_argument(
        "--client-id",
        default=os.getenv("ITAU_SANDBOX_CLIENT_ID"),
        help="Client ID obtido no portal do Itaú (ou defina ITAU_SANDBOX_CLIENT_ID).",
    )
    parser.add_argument(
        "--client-secret",
        default=os.getenv("ITAU_SANDBOX_CLIENT_SECRET"),
        help=(
            "Client secret obtido no portal do Itaú (ou defina ITAU_SANDBOX_CLIENT_SECRET)."
        ),
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Exibe o JSON completo da resposta em vez de somente o access_token.",
    )
    args = parser.parse_args(argv)

    if not args.client_id or not args.client_secret:
        parser.error(
            "Informe --client-id e --client-secret ou configure as variáveis "
            "de ambiente ITAU_SANDBOX_CLIENT_ID / ITAU_SANDBOX_CLIENT_SECRET."
        )
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    try:
        payload = request_token(args.client_id, args.client_secret)
    except Exception as exc:  # pragma: no cover - network failures
        print(f"Erro ao solicitar token: {exc}", file=sys.stderr)
        return 1

    if args.raw:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        token = payload.get("access_token")
        if not token:
            print(
                "Resposta não contém 'access_token'. Use --raw para visualizar o JSON.",
                file=sys.stderr,
            )
            return 1
        print(token)

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
