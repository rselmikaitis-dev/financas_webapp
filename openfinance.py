"""Client helper for Itaú Open Finance APIs."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests


class OpenFinanceError(RuntimeError):
    """Raised when the Open Finance API returns an error."""


@dataclass
class ItauOpenFinanceConfig:
    """Configuration payload used by :class:`ItauOpenFinanceClient`."""

    client_id: str
    client_secret: str
    consent_id: Optional[str] = None
    base_url: str = "https://api.itau/open-finance"
    token_url: str = "https://sts.itau.com.br/api/oauth/token"
    scope: str = "openid accounts"
    certificate: Optional[str] = None
    certificate_key: Optional[str] = None
    accounts_endpoint: str = "/open-banking/accounts/v1/accounts"
    transactions_endpoint: str = (
        "/open-banking/accounts/v1/accounts/{account_id}/transactions"
    )
    consents_endpoint: str = "/open-banking/consents/v1/consents"
    additional_headers: Dict[str, str] = field(default_factory=dict)
    timeout: int = 30
    static_access_token: Optional[str] = None
    static_token_expires_at: Optional[str] = None

    def cert(self) -> Optional[Tuple[str, str] | str]:
        """Return the ``cert`` tuple expected by :mod:`requests`."""

        if self.certificate and self.certificate_key:
            return (self.certificate, self.certificate_key)
        if self.certificate:
            return self.certificate
        return None

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ItauOpenFinanceConfig":
        """Build a config from a dictionary, ignoring unknown keys."""

        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        data = {k: v for k, v in payload.items() if k in allowed}
        return cls(**data)  # type: ignore[arg-type]


class ItauOpenFinanceClient:
    """Small helper to request Itaú Open Finance endpoints."""

    def __init__(self, config: ItauOpenFinanceConfig):
        self.config = config
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None

    # -------------------------
    # Authentication helpers
    # -------------------------
    def get_access_token(self) -> str:
        """Return a cached OAuth access token."""

        static_token = self.config.static_access_token
        if static_token:
            if self._token_expiry is None and self.config.static_token_expires_at:
                self._token_expiry = self._parse_static_expiry(
                    self.config.static_token_expires_at
                )
            if self._token_expiry and datetime.utcnow() >= self._token_expiry:
                raise OpenFinanceError(
                    "Token estático expirado. Atualize o campo 'static_access_token'."
                )
            self._access_token = static_token
            return static_token

        if self._access_token and self._token_expiry:
            if datetime.utcnow() < self._token_expiry:
                return self._access_token

        token, expires_in = self._fetch_access_token()
        self._access_token = token
        self._token_expiry = datetime.utcnow() + timedelta(seconds=max(expires_in - 60, 0))
        return token

    def _parse_static_expiry(self, raw_value: str) -> Optional[datetime]:
        raw_value = raw_value.strip()
        if not raw_value:
            return None

        if raw_value.isdigit():
            return datetime.utcfromtimestamp(int(raw_value))

        try:
            candidate = raw_value
            if candidate.endswith("Z"):
                candidate = candidate[:-1] + "+00:00"
            dt = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise OpenFinanceError(
                "Não foi possível interpretar 'static_token_expires_at'. Use ISO 8601 ou timestamp Unix."
            ) from exc

        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    def _fetch_access_token(self) -> Tuple[str, int]:
        payload = {"grant_type": "client_credentials"}
        if self.config.scope:
            payload["scope"] = self.config.scope
        if self.config.consent_id:
            payload["consent_id"] = self.config.consent_id

        try:
            response = requests.post(
                self.config.token_url,
                data=payload,
                auth=(self.config.client_id, self.config.client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                cert=self.config.cert(),
                timeout=self.config.timeout,
            )
        except requests.RequestException as exc:  # pragma: no cover - network errors
            raise OpenFinanceError(f"Erro ao obter token OAuth: {exc}") from exc

        if response.status_code != 200:
            raise OpenFinanceError(
                f"Token OAuth falhou ({response.status_code}): {response.text}"
            )

        data = response.json()
        token = data.get("access_token")
        expires_in = int(data.get("expires_in", 1800))
        if not token:
            raise OpenFinanceError("Resposta de token sem 'access_token'.")
        return token, expires_in

    # -------------------------
    # HTTP helper
    # -------------------------
    def _resolve_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
    ) -> requests.Response:
        url = self._resolve_url(path)
        headers = headers.copy() if headers else {}
        headers.setdefault("Authorization", f"Bearer {self.get_access_token()}")
        headers.setdefault("Accept", "application/json")
        headers.update(self.config.additional_headers)

        try:
            response = requests.request(
                method,
                url,
                params=params,
                headers=headers,
                json=json,
                data=data,
                cert=self.config.cert(),
                timeout=self.config.timeout,
            )
        except requests.RequestException as exc:  # pragma: no cover - network errors
            raise OpenFinanceError(f"Falha na chamada HTTP: {exc}") from exc

        if response.status_code >= 400:
            if response.status_code == 403:
                raise OpenFinanceError(
                    "Erro 403 ao chamar Itaú Open Finance. Verifique se o consentimento está autorizado, se o token usa o mesmo consentId e revise o guia em 'docs/itau_open_finance_consent.md'."
                )
            raise OpenFinanceError(
                f"Erro {response.status_code} ao chamar {url}: {response.text}"
            )
        return response

    # -------------------------
    # Public API
    # -------------------------
    def list_accounts(self, page_size: int = 200) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"page-size": page_size}
        response = self._request("GET", self.config.accounts_endpoint, params=params)
        payload = response.json()
        data = payload.get("data")
        if isinstance(data, dict) and "accounts" in data:
            accounts = data.get("accounts", [])
        else:
            accounts = data or []
        if not isinstance(accounts, list):
            raise OpenFinanceError("Resposta inesperada ao listar contas.")
        return accounts

    def fetch_transactions(
        self,
        account_id: str,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        page_size: int = 200,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if not account_id:
            raise ValueError("'account_id' é obrigatório.")

        endpoint = self.config.transactions_endpoint.format(account_id=account_id)
        params: Dict[str, Any] = {"page-size": page_size}
        if extra_params:
            params.update({k: v for k, v in extra_params.items() if v is not None})
        if start_date:
            params["fromBookingDate"] = start_date
        if end_date:
            params["toBookingDate"] = end_date

        transactions: List[Dict[str, Any]] = []
        next_url: Optional[str] = endpoint
        next_params: Optional[Dict[str, Any]] = params

        while next_url:
            response = self._request("GET", next_url, params=next_params)
            payload = response.json()
            data = payload.get("data")
            if isinstance(data, dict):
                current = data.get("transactions") or data.get("items") or []
            else:
                current = data or []
            if not isinstance(current, list):
                raise OpenFinanceError("Estrutura inesperada na resposta de transações.")
            transactions.extend(current)

            links = payload.get("links") or {}
            next_link = links.get("next")
            if next_link:
                next_url = next_link
                next_params = None
            else:
                next_url = None

        return transactions

    def create_consent(
        self,
        *,
        permissions: Optional[List[str]] = None,
        expiration_datetime: Optional[str] = None,
        transaction_from_datetime: Optional[str] = None,
        transaction_to_datetime: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a consent using the configured credentials."""

        body: Dict[str, Any] = {
            "data": {
                "permissions": permissions
                or [
                    "ACCOUNTS_READ",
                    "ACCOUNTS_BALANCES_READ",
                    "ACCOUNTS_TRANSACTIONS_READ",
                    "ACCOUNTS_STATEMENTS_READ",
                ]
            }
        }
        data_payload = body["data"]
        if expiration_datetime:
            data_payload["expirationDateTime"] = expiration_datetime
        if transaction_from_datetime:
            data_payload["transactionFromDateTime"] = transaction_from_datetime
        if transaction_to_datetime:
            data_payload["transactionToDateTime"] = transaction_to_datetime

        response = self._request(
            "POST",
            self.config.consents_endpoint,
            json=body,
        )
        payload = response.json()
        data = payload.get("data") or {}
        consent_id = data.get("consentId") or payload.get("consentId")
        if not consent_id:
            raise OpenFinanceError("Resposta de consentimento sem 'consentId'.")
        return payload


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        s = str(value).replace(".", "").replace(",", ".")
        return float(s)
    except Exception:
        return None


def transactions_to_dataframe(transactions: List[Dict[str, Any]]) -> "pd.DataFrame":
    """Convert the API payload into a pandas DataFrame."""

    import pandas as pd

    rows: List[Dict[str, Any]] = []
    for item in transactions:
        amount_payload = item.get("amount")
        value = None
        if isinstance(amount_payload, dict):
            value = _safe_float(amount_payload.get("amount"))
        else:
            value = _safe_float(amount_payload)
        if value is None:
            continue

        sign_hint = str(item.get("creditDebitType") or item.get("type") or "").lower()
        if "debit" in sign_hint or "debito" in sign_hint:
            value = -abs(value)
        elif "credit" in sign_hint or "credito" in sign_hint:
            value = abs(value)
        else:
            # Alguns payloads já trazem o sinal correto.
            pass

        description = (
            item.get("description")
            or item.get("transactionName")
            or item.get("transactionType")
            or item.get("additionalInfo")
            or item.get("type")
            or ""
        )
        data = (
            item.get("bookingDate")
            or item.get("transactionDate")
            or item.get("valueDateTime")
            or item.get("effectiveDate")
            or item.get("date")
        )

        row: Dict[str, Any] = {
            "Data": data,
            "Descrição": description,
            "Valor": value,
        }
        tx_id = item.get("transactionId") or item.get("id")
        if tx_id:
            row["Transação ID"] = str(tx_id)
        rows.append(row)

    if not rows:
        return pd.DataFrame(columns=["Data", "Descrição", "Valor"])

    df = pd.DataFrame(rows)
    return df
