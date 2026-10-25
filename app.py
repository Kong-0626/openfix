"""Zero-dependency HTTP server for the OpenFix competition prototype."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from openfix.engine import MaintenanceEngine  # noqa: E402
from openfix.evaluate import evaluate_engine  # noqa: E402
from openfix.store import WorkOrderStore  # noqa: E402


MAX_BODY_BYTES = 16 * 1024
APPROVAL_CONFIRMATION = "确认安全条件并批准工单"
WORK_ORDER_ID = re.compile(r"^WO-\d{8}-[A-F0-9]{6}$")

ENGINE = MaintenanceEngine(ROOT / "data")
DATABASE_PATH = Path(os.environ.get("OPENFIX_DB_PATH", ROOT / "data" / "runtime" / "openfix.db"))
STORE = WorkOrderStore(DATABASE_PATH)
EVALUATION_CACHE: dict | None = None


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class OpenFixHandler(BaseHTTPRequestHandler):
    server_version = "OpenFix/0.1"
    sys_version = ""

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api_get(parsed)
            return
        self._serve_static(parsed.path)

    def do_HEAD(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._json_response(
                HTTPStatus.METHOD_NOT_ALLOWED,
                {"ok": False, "error": "API 端点不支持 HEAD 请求"},
                head_only=True,
            )
            return
        self._serve_static(parsed.path, head_only=True)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self._json_response(HTTPStatus.NOT_FOUND, {"ok": False, "error": "接口不存在"})
            return
        try:
            payload = self._read_json()
            if parsed.path == "/api/diagnose":
                query = payload.get("query")
                asset_id = payload.get("asset_id") or None
                if not isinstance(query, str):
                    raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "query 必须是字符串")
                if asset_id is not None and not isinstance(asset_id, str):
                    raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "asset_id 格式错误")
                result = ENGINE.diagnose(query, asset_id).to_dict()
                self._json_response(HTTPStatus.OK, {"ok": True, "data": result})
                return
            if parsed.path == "/api/work-orders":
                self._create_work_order(payload)
                return
            match = re.fullmatch(r"/api/work-orders/([^/]+)/(approve|reject)", parsed.path)
            if match:
                self._decide_work_order(match.group(1), match.group(2), payload)
                return
            self._json_response(HTTPStatus.NOT_FOUND, {"ok": False, "error": "接口不存在"})
        except ApiError as error:
            self._json_response(error.status, {"ok": False, "error": error.message})
        except ValueError as error:
            self._json_response(HTTPStatus.UNPROCESSABLE_ENTITY, {"ok": False, "error": str(error)})
        except Exception:
            traceback.print_exc()
            self._json_response(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "服务器内部错误"})

    def _handle_api_get(self, parsed) -> None:
        try:
            if parsed.path == "/api/health":
                data = {"status": "ok", "service": "OpenFix", "version": "0.1.0"}
            elif parsed.path == "/api/overview":
                data = ENGINE.overview()
            elif parsed.path == "/api/work-orders":
                query = parse_qs(parsed.query)
                limit = self._bounded_int(query.get("limit", ["20"])[0], 1, 100)
                data = STORE.list_work_orders(limit)
            elif parsed.path == "/api/audit":
                query = parse_qs(parsed.query)
                limit = self._bounded_int(query.get("limit", ["30"])[0], 1, 100)
                data = STORE.list_audit_events(limit)
            elif parsed.path == "/api/evaluation":
                global EVALUATION_CACHE
                if EVALUATION_CACHE is None:
                    EVALUATION_CACHE = evaluate_engine(ENGINE)
                data = EVALUATION_CACHE
            else:
                self._json_response(HTTPStatus.NOT_FOUND, {"ok": False, "error": "接口不存在"})
                return
            self._json_response(HTTPStatus.OK, {"ok": True, "data": data})
        except Exception:
            traceback.print_exc()
            self._json_response(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "服务器内部错误"})

    def _create_work_order(self, payload: dict) -> None:
        diagnosis_id = self._required_string(payload, "diagnosis_id", 80)
        summary = self._required_string(payload, "summary", 500)
        title = self._required_string(payload, "title", 120)
        priority = payload.get("priority", "P2")
        if priority not in {"P1", "P2", "P3", "P4"}:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "priority 必须为 P1-P4")
        asset_id = payload.get("asset_id")
        if asset_id is not None and (not isinstance(asset_id, str) or len(asset_id) > 40):
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "asset_id 格式错误")
        actions = payload.get("actions", [])
        if not isinstance(actions, list) or not all(isinstance(item, dict) for item in actions):
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "actions 必须为对象数组")
        if len(actions) > 12:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "actions 最多 12 条")
        evidence_ids = payload.get("evidence_ids", [])
        if not isinstance(evidence_ids, list) or not all(
            isinstance(item, str) and len(item) <= 60 for item in evidence_ids
        ):
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "evidence_ids 格式错误")
        if len(evidence_ids) > 10:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "evidence_ids 最多 10 个")
        actor = self._required_string(payload, "actor", 40)
        work_order = STORE.create_work_order(
            asset_id=asset_id,
            priority=priority,
            title=title,
            summary=summary,
            diagnosis_id=diagnosis_id,
            actions=actions,
            evidence_ids=evidence_ids,
            actor=actor,
        )
        self._json_response(HTTPStatus.CREATED, {"ok": True, "data": work_order})

    def _decide_work_order(self, work_order_id: str, decision: str, payload: dict) -> None:
        if not WORK_ORDER_ID.fullmatch(work_order_id):
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "工单编号格式错误")
        approver = self._required_string(payload, "approver", 40)
        if len(approver.strip()) < 2:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "审批人姓名至少 2 个字符")
        if decision == "approve":
            confirmation = self._required_string(payload, "confirmation", 60)
            if confirmation != APPROVAL_CONFIRMATION:
                raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "请完成安全条件确认")
            result = STORE.approve_work_order(work_order_id, approver, confirmation)
        else:
            reason = self._required_string(payload, "reason", 200)
            result = STORE.reject_work_order(work_order_id, approver, reason)
        if result is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "工单不存在")
        self._json_response(HTTPStatus.OK, {"ok": True, "data": result})

    def _read_json(self) -> dict:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            raise ApiError(HTTPStatus.LENGTH_REQUIRED, "缺少 Content-Length")
        try:
            length = int(content_length)
        except ValueError as error:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Content-Length 格式错误") from error
        if length <= 0:
            raise ApiError(HTTPStatus.BAD_REQUEST, "请求体不能为空")
        if length > MAX_BODY_BYTES:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "请求体超过 16KB")
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ApiError(HTTPStatus.BAD_REQUEST, "请求体必须是 UTF-8 JSON") from error
        if not isinstance(value, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "JSON 根节点必须是对象")
        return value

    def _serve_static(self, request_path: str, head_only: bool = False) -> None:
        relative = unquote(request_path)
        if relative == "/":
            relative = "/index.html"
        web_root = (ROOT / "web").resolve()
        target = (web_root / relative.lstrip("/")).resolve()
        if web_root not in target.parents and target != web_root:
            self._json_response(HTTPStatus.FORBIDDEN, {"ok": False, "error": "禁止访问"})
            return
        if not target.is_file():
            self._json_response(HTTPStatus.NOT_FOUND, {"ok": False, "error": "页面不存在"})
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        content = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._security_headers()
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache" if target.name == "index.html" else "public, max-age=3600")
        self.end_headers()
        if not head_only:
            self.wfile.write(content)

    def _json_response(self, status: HTTPStatus, payload: dict, head_only: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )

    @staticmethod
    def _required_string(payload: dict, key: str, max_length: int) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, f"{key} 不能为空")
        value = value.strip()
        if len(value) > max_length:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, f"{key} 不能超过 {max_length} 字符")
        return value

    @staticmethod
    def _bounded_int(value: str, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except ValueError as error:
            raise ApiError(HTTPStatus.BAD_REQUEST, "limit 必须是整数") from error
        return max(minimum, min(parsed, maximum))

    def log_message(self, message: str, *args) -> None:
        if os.environ.get("OPENFIX_QUIET") != "1":
            print(f"[OpenFix] {self.address_string()} {message % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the OpenFix demo server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), OpenFixHandler)
    print(f"OpenFix running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
