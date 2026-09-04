from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar, Protocol

from afterimage.contracts.models import AccountSnapshot, ExecutionIntent

from .alpaca_gateway import AccountPreflight, PreflightFailure
from .private_file import (
    PrivateFileInvalid,
    PrivateFileMissing,
    read_private_bytes,
    read_private_text,
)


@dataclass(frozen=True)
class CLIResult:
    stdout: str
    json: Any | None = None


class CLICommandError(RuntimeError):
    """A deliberately non-reflective CLI failure.

    stderr may contain request metadata in verbose third-party clients.  It is
    retained for diagnostics on the object, but never interpolated into the
    exception text or API response.
    """

    def __init__(self, command: tuple[str, ...], returncode: int, stderr: str) -> None:
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"CLI_COMMAND_FAILED command={' '.join(command)} code={returncode}")


class CLIRunner(Protocol):
    async def run(self, *arguments: str) -> CLIResult: ...


class SubprocessCLIRunner:
    CHILD_ENV_ALLOWLIST: ClassVar[frozenset[str]] = frozenset(
        {
            "HOME",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "LOGNAME",
            "NO_PROXY",
            "PATH",
            "SSL_CERT_DIR",
            "SSL_CERT_FILE",
            "TEMP",
            "TMP",
            "TMPDIR",
            "USER",
            "XDG_CACHE_HOME",
            "XDG_CONFIG_HOME",
        }
    )

    def __init__(
        self,
        executable: str | Path,
        profile: str = "afterimage-paper",
        timeout_seconds: float = 30.0,
        expected_sha256: str | None = None,
    ) -> None:
        self.executable = str(executable)
        self.profile = profile
        self.timeout_seconds = timeout_seconds
        self.expected_sha256 = expected_sha256
        self._locked_config: tempfile.TemporaryDirectory[str] | None = None

    @staticmethod
    def _write_private_file(path: Path, payload: bytes) -> None:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            os.write(descriptor, payload)
        finally:
            os.close(descriptor)

    def freeze_configuration(self) -> None:
        """Give every subprocess one private, immutable-at-source profile snapshot."""
        if self._locked_config is not None:
            return
        configured = os.getenv("ALPACA_CONFIG_DIR", "").strip()
        if configured:
            source = Path(configured)
        else:
            xdg = os.getenv("XDG_CONFIG_HOME", "").strip()
            source = Path(xdg) / "alpaca" if xdg else Path.home() / ".config" / "alpaca"
        try:
            config_payload = read_private_bytes(source / "config.yaml")
            profile_payload = read_private_bytes(source / "profiles" / f"{self.profile}.yaml")
        except (PrivateFileMissing, PrivateFileInvalid) as exc:
            raise CLICommandError(("profile-snapshot",), 126, "invalid profile") from exc

        locked = tempfile.TemporaryDirectory(prefix="afterimage-alpaca-cli-")
        root = Path(locked.name)
        os.chmod(root, 0o700)
        profiles = root / "profiles"
        profiles.mkdir(mode=0o700)
        self._write_private_file(root / "config.yaml", config_payload)
        self._write_private_file(profiles / f"{self.profile}.yaml", profile_payload)
        self._locked_config = locked

    def close(self) -> None:
        if self._locked_config is not None:
            self._locked_config.cleanup()
            self._locked_config = None

    def _verify_executable(self) -> None:
        if not self.expected_sha256:
            return
        path = Path(self.executable)
        try:
            metadata = path.lstat()
            payload = path.read_bytes()
        except OSError as exc:
            raise CLICommandError(("binary-integrity",), 126, "unreadable") from exc
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise CLICommandError(("binary-integrity",), 126, "invalid type")
        if metadata.st_mode & 0o022:
            raise CLICommandError(("binary-integrity",), 126, "writable by group/other")
        observed = hashlib.sha256(payload).hexdigest()
        if not secrets.compare_digest(observed, self.expected_sha256):
            raise CLICommandError(("binary-integrity",), 126, "checksum mismatch")

    def _child_environment(self) -> dict[str, str]:
        inherited = {
            key: value for key, value in os.environ.items() if key in self.CHILD_ENV_ALLOWLIST
        }
        environment = {**inherited, "ALPACA_PAPER_TRADE": "true", "NO_COLOR": "1"}
        if self._locked_config is not None:
            environment["ALPACA_CONFIG_DIR"] = self._locked_config.name
        return environment

    async def run(self, *arguments: str) -> CLIResult:
        self._verify_executable()
        command = (self.executable, "--profile", self.profile, *arguments)
        environment = self._child_environment()
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
            )
            stdout_raw, stderr_raw = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout_seconds
            )
        except FileNotFoundError as exc:
            raise CLICommandError(tuple(arguments), 127, "binary not found") from exc
        except TimeoutError as exc:
            if "process" in locals():
                process.kill()
                await process.wait()
            raise CLICommandError(tuple(arguments), 124, "timeout") from exc
        stdout = stdout_raw.decode("utf-8", errors="replace").strip()
        stderr = stderr_raw.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            raise CLICommandError(tuple(arguments), int(process.returncode or 1), stderr)
        parsed: Any | None = None
        if stdout:
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError:
                parsed = None
        return CLIResult(stdout=stdout, json=parsed)


class AlpacaCLIGateway:
    """Official Alpaca CLI adapter with a separate, default-deny write boundary."""

    READ_CAPABILITIES: ClassVar[dict[str, str]] = {
        "account": "account get",
        "account_config": "account config get",
        "orders": "order list",
        "positions": "position list",
        "clock": "clock",
        "stock_bars": "data bars",
        "stock_snapshot": "data snapshot",
        "news": "data news",
        "option_contracts": "option contracts",
        "option_chain": "data option chain",
        "option_quotes": "data option latest-quotes",
    }
    PAPER_TRADING_ENDPOINT: ClassVar[str] = "https://paper-api.alpaca.markets"

    def __init__(
        self,
        runner: CLIRunner,
        account_binding_path: str | Path = ".afterimage/alpaca-account.sha256",
        execution_enabled: bool = False,
        paper: bool = True,
    ) -> None:
        if not paper:
            raise PreflightFailure("ALPACA_PAPER_TRADE_MUST_BE_TRUE")
        self.runner = runner
        self.account_binding_path = Path(account_binding_path)
        self.execution_enabled = execution_enabled
        self.paper = paper
        self.version = "unknown"
        self.paper_endpoint_verified = False

    async def connect(self) -> None:
        freeze_configuration = getattr(self.runner, "freeze_configuration", None)
        if callable(freeze_configuration):
            freeze_configuration()
        result = await self.runner.run("version")
        self.version = result.stdout.strip()
        if not self.version:
            raise PreflightFailure("ALPACA_CLI_VERSION_MISSING")
        doctor = await self.runner.run("doctor")
        endpoint_line = " ".join(doctor.stdout.lower().split())
        if f"trading: {self.PAPER_TRADING_ENDPOINT}" not in endpoint_line:
            raise PreflightFailure("ALPACA_CLI_NOT_PAPER_ENDPOINT")
        self.paper_endpoint_verified = True

    async def close(self) -> None:
        close_runner = getattr(self.runner, "close", None)
        if callable(close_runner):
            close_runner()

    @staticmethod
    def _object(result: CLIResult, reason: str) -> dict[str, Any]:
        if not isinstance(result.json, dict):
            raise PreflightFailure(reason)
        value = result.json.get("account", result.json.get("data", result.json))
        if not isinstance(value, dict):
            raise PreflightFailure(reason)
        return value

    @staticmethod
    def _list(result: CLIResult, *keys: str) -> tuple[dict[str, Any], ...]:
        value = result.json
        if isinstance(value, dict):
            for key in keys:
                if key in value:
                    value = value[key]
                    break
        if not isinstance(value, list):
            return ()
        return tuple(item for item in value if isinstance(item, dict))

    @classmethod
    def _required_list(
        cls, result: CLIResult, keys: tuple[str, ...], reason: str
    ) -> tuple[dict[str, Any], ...]:
        value = result.json
        if isinstance(value, list):
            if not all(isinstance(item, dict) for item in value):
                raise PreflightFailure(reason)
            return tuple(value)
        if isinstance(value, dict):
            matched = [key for key in keys if key in value]
            if len(matched) != 1:
                raise PreflightFailure(reason)
            nested = value[matched[0]]
            if isinstance(nested, list) and all(isinstance(item, dict) for item in nested):
                return tuple(nested)
            raise PreflightFailure(reason)
        raise PreflightFailure(reason)

    async def _account_and_hash(self) -> tuple[dict[str, Any], str]:
        account = self._object(
            await self.runner.run("account", "get", "--quiet"),
            "MALFORMED_ACCOUNT_PREFLIGHT",
        )
        raw_id = str(account.get("id", account.get("account_id", ""))).strip()
        if not raw_id:
            raise PreflightFailure("ACCOUNT_ID_MISSING")
        return account, hashlib.sha256(raw_id.encode()).hexdigest()

    async def bind_account(self) -> str:
        """Pin the selected OAuth paper account by a one-way identifier."""
        if not self.paper_endpoint_verified:
            raise PreflightFailure("PAPER_ENDPOINT_NOT_VERIFIED")
        _, account_hash = await self._account_and_hash()
        self.account_binding_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.account_binding_path.parent, 0o700)
        if self.account_binding_path.is_symlink():
            raise PreflightFailure("ALPACA_ACCOUNT_BINDING_SYMLINK")
        descriptor = os.open(
            self.account_binding_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "schema": "afterimage-alpaca-binding-v1",
                        "account_id_hash": account_hash,
                        "trading_endpoint": self.PAPER_TRADING_ENDPOINT,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            handle.write("\n")
        os.chmod(self.account_binding_path, 0o600)
        return account_hash

    def bound_account_hash(self) -> str:
        try:
            value = read_private_text(self.account_binding_path).strip()
        except PrivateFileMissing as exc:
            raise PreflightFailure("ALPACA_ACCOUNT_NOT_BOUND") from exc
        except PrivateFileInvalid as exc:
            raise PreflightFailure("ALPACA_ACCOUNT_BINDING_INVALID") from exc
        try:
            binding = json.loads(value)
        except json.JSONDecodeError as exc:
            raise PreflightFailure("ALPACA_ACCOUNT_BINDING_INVALID") from exc
        if not isinstance(binding, dict):
            raise PreflightFailure("ALPACA_ACCOUNT_BINDING_INVALID")
        account_hash = str(binding.get("account_id_hash", ""))
        endpoint = str(binding.get("trading_endpoint", ""))
        if len(account_hash) != 64 or endpoint != self.PAPER_TRADING_ENDPOINT:
            raise PreflightFailure("ALPACA_ACCOUNT_BINDING_INVALID")
        return account_hash

    async def preflight(
        self,
        expected_account_id_hash: str | None = None,
        allow_existing_exposure: bool | None = None,
    ) -> AccountPreflight:
        if not self.paper_endpoint_verified:
            raise PreflightFailure("PAPER_ENDPOINT_NOT_VERIFIED")
        expected = expected_account_id_hash or self.bound_account_hash()
        (
            account_result,
            config_result,
            orders_result,
            positions_result,
            clock_result,
        ) = await asyncio.gather(
            self.runner.run("account", "get", "--quiet"),
            self.runner.run("account", "config", "get", "--quiet"),
            self.runner.run("order", "list", "--status", "open", "--limit", "100", "--quiet"),
            self.runner.run("position", "list", "--quiet"),
            self.runner.run("clock", "--quiet"),
        )
        account = self._object(account_result, "MALFORMED_ACCOUNT_PREFLIGHT")
        config = self._object(config_result, "MALFORMED_ACCOUNT_CONFIG")
        if account.get("last_equity") is None:
            raise PreflightFailure("ACCOUNT_LAST_EQUITY_MISSING")
        raw_id = str(account.get("id", account.get("account_id", ""))).strip()
        account_hash = hashlib.sha256(raw_id.encode()).hexdigest()
        if not raw_id or account_hash != expected:
            raise PreflightFailure("ACCOUNT_ID_MISMATCH")
        approved = int(
            account.get("options_approved_level", config.get("max_options_trading_level", 0)) or 0
        )
        effective = int(account.get("options_trading_level", approved) or approved)
        if min(approved, effective) < 3:
            raise PreflightFailure("OPTIONS_LEVEL_3_REQUIRED")
        if str(account.get("status", "UNKNOWN")).upper() != "ACTIVE":
            raise PreflightFailure("ACCOUNT_INACTIVE")
        trading_blocked = bool(account.get("trading_blocked", config.get("suspend_trade", False)))
        if trading_blocked:
            raise PreflightFailure("TRADING_BLOCKED")
        open_orders = self._required_list(
            orders_result, ("orders", "items"), "MALFORMED_OPEN_ORDERS"
        )
        positions = self._required_list(
            positions_result, ("positions", "items"), "MALFORMED_POSITIONS"
        )
        allow_exposure = (
            allow_existing_exposure
            if allow_existing_exposure is not None
            else os.getenv("AFTERIMAGE_ALLOW_EXISTING_PAPER_EXPOSURE", "false").lower() == "true"
        )
        if not allow_exposure and (open_orders or positions):
            raise PreflightFailure(
                f"UNKNOWN_PAPER_EXPOSURE orders={len(open_orders)} positions={len(positions)}"
            )
        if not isinstance(clock_result.json, dict):
            raise PreflightFailure("MALFORMED_MARKET_CLOCK")
        snapshot = AccountSnapshot(
            account_id_hash=account_hash,
            paper=True,
            status=str(account.get("status", "UNKNOWN")),
            equity=Decimal(str(account.get("equity", "0"))),
            last_equity=Decimal(str(account.get("last_equity", "0"))),
            cash=Decimal(str(account.get("cash", "0"))),
            options_buying_power=Decimal(str(account.get("options_buying_power", "0"))),
            options_approved_level=approved,
            options_trading_level=effective,
            trading_blocked=trading_blocked,
            timestamp=datetime.now(UTC),
        )
        return AccountPreflight(
            account=snapshot,
            market_open=bool(clock_result.json.get("is_open", False)),
            clock=clock_result.json,
            open_orders=open_orders,
            positions=positions,
            capabilities={
                **self.READ_CAPABILITIES,
                "execution": "enabled" if self.execution_enabled else "disabled",
                "transport": f"alpaca-cli/{self.version}",
            },
        )

    async def stock_bars(
        self, symbol: str, start: datetime, end: datetime, timeframe: str = "5Min"
    ) -> list[dict[str, Any]]:
        base_arguments = [
            "data",
            "bars",
            "--symbol",
            symbol,
            "--start",
            start.isoformat(),
            "--end",
            end.isoformat(),
            "--timeframe",
            timeframe,
            "--feed",
            os.getenv("AFTERIMAGE_STOCK_FEED", "iex"),
            "--limit",
            "10000",
        ]
        bars: list[dict[str, Any]] = []
        page_token = ""
        observed_tokens: set[str] = set()
        while True:
            arguments = list(base_arguments)
            if page_token:
                arguments.extend(("--page-token", page_token))
            result = await self.runner.run(*arguments, "--quiet")
            if not isinstance(result.json, dict):
                raise PreflightFailure("MALFORMED_STOCK_BARS")
            value = result.json.get("bars", result.json.get(symbol, result.json.get("data")))
            if isinstance(value, dict):
                value = value.get(symbol)
            if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
                raise PreflightFailure("MALFORMED_STOCK_BARS")
            bars.extend(value)
            next_token = str(result.json.get("next_page_token", "") or "")
            if not next_token:
                return bars
            if next_token in observed_tokens:
                raise PreflightFailure("STOCK_BARS_PAGINATION_LOOP")
            observed_tokens.add(next_token)
            page_token = next_token

    async def stock_snapshot(self, symbol: str) -> dict[str, Any]:
        normalized = symbol.strip().upper()
        if not normalized:
            raise PreflightFailure("STOCK_SYMBOL_REQUIRED")
        result = await self.runner.run(
            "data",
            "snapshot",
            "--symbol",
            normalized,
            "--feed",
            os.getenv("AFTERIMAGE_STOCK_FEED", "iex"),
            "--quiet",
        )
        if not isinstance(result.json, dict):
            raise PreflightFailure("MALFORMED_STOCK_SNAPSHOT")
        return result.json

    async def option_contracts(self, symbol: str, **filters: Any) -> list[dict[str, Any]]:
        base_arguments = ["option", "contracts", "--underlying-symbols", symbol]
        mapping = {
            "expiration_date": "--expiration-date",
            "expiration_date_gte": "--expiration-date-gte",
            "expiration_date_lte": "--expiration-date-lte",
            "strike_price_gte": "--strike-price-gte",
            "strike_price_lte": "--strike-price-lte",
            "type": "--type",
            "status": "--status",
            "limit": "--limit",
        }
        for key, flag in mapping.items():
            if filters.get(key) is not None:
                base_arguments.extend((flag, str(filters[key])))
        contracts: list[dict[str, Any]] = []
        page_token = ""
        observed_tokens: set[str] = set()
        while True:
            arguments = list(base_arguments)
            if page_token:
                arguments.extend(("--page-token", page_token))
            result = await self.runner.run(*arguments, "--quiet")
            if not isinstance(result.json, dict):
                raise PreflightFailure("MALFORMED_OPTION_CONTRACTS")
            value = result.json.get(
                "option_contracts",
                result.json.get("contracts", result.json.get("data")),
            )
            if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
                raise PreflightFailure("MALFORMED_OPTION_CONTRACTS")
            contracts.extend(value)
            next_token = str(result.json.get("next_page_token", "") or "")
            if not next_token:
                return contracts
            if next_token in observed_tokens:
                raise PreflightFailure("OPTION_CONTRACTS_PAGINATION_LOOP")
            observed_tokens.add(next_token)
            page_token = next_token

    async def option_bars(
        self,
        symbols: tuple[str, ...],
        start: datetime,
        end: datetime,
        timeframe: str = "5Min",
    ) -> list[dict[str, Any]]:
        if not symbols or len(symbols) > 100:
            raise PreflightFailure("OPTION_BAR_SYMBOL_COUNT_INVALID")
        base_arguments = [
            "data",
            "option",
            "bars",
            "--symbols",
            ",".join(symbols),
            "--start",
            start.isoformat(),
            "--end",
            end.isoformat(),
            "--timeframe",
            timeframe,
            "--limit",
            "10000",
        ]
        bars: list[dict[str, Any]] = []
        page_token = ""
        observed_tokens: set[str] = set()
        while True:
            arguments = list(base_arguments)
            if page_token:
                arguments.extend(("--page-token", page_token))
            result = await self.runner.run(*arguments, "--quiet")
            if not isinstance(result.json, dict):
                raise PreflightFailure("MALFORMED_OPTION_BARS")
            value = result.json.get("bars")
            if not isinstance(value, dict):
                raise PreflightFailure("MALFORMED_OPTION_BARS")
            for contract_symbol, contract_bars in value.items():
                if contract_symbol not in symbols or not isinstance(contract_bars, list):
                    raise PreflightFailure("MALFORMED_OPTION_BARS")
                for item in contract_bars:
                    if not isinstance(item, dict):
                        raise PreflightFailure("MALFORMED_OPTION_BARS")
                    bars.append({"symbol": contract_symbol, **item})
            next_token = str(result.json.get("next_page_token", "") or "")
            if not next_token:
                return bars
            if next_token in observed_tokens:
                raise PreflightFailure("OPTION_BARS_PAGINATION_LOOP")
            observed_tokens.add(next_token)
            page_token = next_token

    async def option_chain(self, symbol: str, **filters: Any) -> dict[str, Any]:
        arguments = [
            "data",
            "option",
            "chain",
            "--underlying-symbol",
            symbol,
            "--feed",
            str(filters.pop("feed", os.getenv("AFTERIMAGE_OPTIONS_FEED", "indicative"))),
            "--quiet",
        ]
        mapping = {
            "expiration_date": "--expiration-date",
            "expiration_date_gte": "--expiration-date-gte",
            "expiration_date_lte": "--expiration-date-lte",
            "strike_price_gte": "--strike-price-gte",
            "strike_price_lte": "--strike-price-lte",
            "type": "--type",
            "limit": "--limit",
        }
        for key, flag in mapping.items():
            if filters.get(key) is not None:
                arguments.extend((flag, str(filters[key])))
        result = await self.runner.run(*arguments)
        if not isinstance(result.json, dict):
            raise PreflightFailure("MALFORMED_OPTION_CHAIN")
        return result.json

    async def option_quotes(self, **arguments: Any) -> dict[str, Any]:
        symbols = arguments.get("symbols", arguments.get("symbol", []))
        joined = ",".join(symbols) if isinstance(symbols, list) else str(symbols)
        result = await self.runner.run(
            "data", "option", "latest-quotes", "--symbols", joined, "--quiet"
        )
        return result.json if isinstance(result.json, dict) else {}

    async def positions(self) -> tuple[dict[str, Any], ...]:
        result = await self.runner.run("position", "list", "--quiet")
        return self._required_list(result, ("positions", "items"), "MALFORMED_POSITIONS")

    async def _reattest_mutation_target(self) -> None:
        """Revalidate the frozen CLI profile and bound account immediately before a write."""
        doctor = await self.runner.run("doctor")
        endpoint_line = " ".join(doctor.stdout.lower().split())
        if f"trading: {self.PAPER_TRADING_ENDPOINT}" not in endpoint_line:
            raise PreflightFailure("ALPACA_CLI_NOT_PAPER_ENDPOINT")
        _, current_hash = await self._account_and_hash()
        if not secrets.compare_digest(current_hash, self.bound_account_hash()):
            raise PreflightFailure("ACCOUNT_ID_MISMATCH")

    @staticmethod
    def _order_arguments(intent: ExecutionIntent, client_order_id: str) -> list[str]:
        if intent.asset_class == "equity":
            if intent.symbol is None or intent.side is None:
                raise PreflightFailure("EQUITY_BRACKET_INCOMPLETE")
            if intent.reduce_only:
                return [
                    "order",
                    "submit",
                    "--symbol",
                    intent.symbol,
                    "--qty",
                    str(intent.quantity),
                    "--side",
                    intent.side,
                    "--type",
                    "market",
                    "--time-in-force",
                    "day",
                    "--client-order-id",
                    client_order_id,
                    "--quiet",
                ]
            if intent.take_profit_price is None or intent.stop_price is None:
                raise PreflightFailure("EQUITY_BRACKET_INCOMPLETE")
            return [
                "order",
                "submit",
                "--symbol",
                intent.symbol,
                "--qty",
                str(intent.quantity),
                "--side",
                intent.side,
                "--type",
                "limit",
                "--limit-price",
                str(intent.limit_price),
                "--time-in-force",
                "day",
                "--order-class",
                "bracket",
                "--take-profit",
                json.dumps({"limit_price": str(intent.take_profit_price)}, separators=(",", ":")),
                "--stop-loss",
                json.dumps({"stop_price": str(intent.stop_price)}, separators=(",", ":")),
                "--client-order-id",
                client_order_id,
                "--quiet",
            ]
        legs = [
            {
                "symbol": leg.symbol,
                "ratio_qty": str(leg.ratio_qty),
                "side": leg.side,
                "position_intent": leg.position_intent,
            }
            for leg in intent.legs
        ]
        return [
            "order",
            "submit",
            "--qty",
            str(intent.quantity),
            "--type",
            "limit",
            "--limit-price",
            str(intent.limit_price),
            "--time-in-force",
            "day",
            "--order-class",
            "mleg",
            "--client-order-id",
            client_order_id,
            "--legs",
            json.dumps(legs, separators=(",", ":")),
            "--quiet",
        ]

    async def dry_run_order(self, intent: ExecutionIntent, client_order_id: str) -> dict[str, Any]:
        arguments = self._order_arguments(intent, client_order_id)
        arguments.append("--dry-run")
        result = await self.runner.run(*arguments)
        return result.json if isinstance(result.json, dict) else {"request": result.stdout}

    async def place_order(self, intent: ExecutionIntent, client_order_id: str) -> dict[str, Any]:
        if not self.execution_enabled:
            raise PreflightFailure("EXECUTION_DISABLED")
        await self._reattest_mutation_target()
        result = await self.runner.run(*self._order_arguments(intent, client_order_id))
        if not isinstance(result.json, dict):
            raise PreflightFailure("MALFORMED_ORDER_RESPONSE")
        return result.json

    async def dry_run_option_order(
        self, intent: ExecutionIntent, client_order_id: str
    ) -> dict[str, Any]:
        return await self.dry_run_order(intent, client_order_id)

    async def place_option_order(
        self, intent: ExecutionIntent, client_order_id: str
    ) -> dict[str, Any]:
        return await self.place_order(intent, client_order_id)

    async def order_by_client_id(self, client_order_id: str) -> dict[str, Any]:
        result = await self.runner.run(
            "order", "get-by-client-id", "--client-order-id", client_order_id, "--quiet"
        )
        return result.json if isinstance(result.json, dict) else {}

    async def replace_order(self, order_id: str, limit_price: Decimal) -> dict[str, Any]:
        if not self.execution_enabled:
            raise PreflightFailure("EXECUTION_DISABLED")
        await self._reattest_mutation_target()
        result = await self.runner.run(
            "order", "replace", order_id, "--limit-price", str(limit_price), "--quiet"
        )
        if not isinstance(result.json, dict):
            raise PreflightFailure("MALFORMED_ORDER_RESPONSE")
        return result.json

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        if not self.execution_enabled:
            raise PreflightFailure("EXECUTION_DISABLED")
        await self._reattest_mutation_target()
        result = await self.runner.run("order", "cancel", order_id, "--quiet")
        if not isinstance(result.json, dict):
            raise PreflightFailure("MALFORMED_ORDER_RESPONSE")
        return result.json
