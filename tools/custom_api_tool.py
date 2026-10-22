import json
import logging
import time
import urllib.parse
from typing import Dict, Any, Tuple, Optional
import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)

BLOCKED_HOSTNAMES = {
    "127.0.0.1", "localhost", "0.0.0.0", "::1", "169.254.169.254", "metadata.google.internal"
}

class CustomApiTool:
    """
    Production-ready Custom REST API / Webhook Connector.
    Enables secure project-scoped connection, custom authentication
    (Bearer, API Key, Basic Auth, Custom Headers), live testing,
    and structured data retrieval with SSRF protection.
    """

    @staticmethod
    def is_safe_url(url: str) -> Tuple[bool, str]:
        """
        Validates URL to protect against Server-Side Request Forgery (SSRF).
        """
        try:
            parsed = urllib.parse.urlparse(url.strip())
            if parsed.scheme.lower() not in ("http", "https"):
                return False, "Only HTTP and HTTPS protocols are supported."
            
            hostname = (parsed.hostname or "").lower()
            if not hostname:
                return False, "Invalid endpoint hostname."
            
            if hostname in BLOCKED_HOSTNAMES:
                return False, f"Access to restricted host '{hostname}' is not permitted."
            
            # Block internal link-local / cloud metadata subnets
            if hostname.startswith("169.254.") or hostname.startswith("127."):
                return False, "Access to loopback or link-local subnet is forbidden."

            return True, ""
        except Exception as e:
            return False, f"Invalid URL structure: {e}"

    @staticmethod
    def parse_config(username_email: str = "", api_token: str = "") -> Dict[str, Any]:
        """
        Extracts structured configuration from database fields.
        Supports both modern JSON config in api_token and legacy/simple formats.
        """
        config = {
            "auth_type": "bearer",
            "token": "",
            "api_key_name": "X-API-Key",
            "api_key_value": "",
            "basic_user": "",
            "basic_pass": "",
            "method": "GET",
            "custom_headers": {},
            "query_params": {},
            "body": "",
            "data_category": "general"
        }

        # If username_email contains auth_type (e.g., 'api_key', 'basic', 'bearer', 'custom_headers', 'none')
        clean_user = (username_email or "").strip().lower()
        if clean_user in ("bearer", "api_key", "basic", "custom_headers", "none"):
            config["auth_type"] = clean_user

        # Try parsing JSON config stored in api_token
        raw_token = (api_token or "").strip()
        if raw_token.startswith("{") and raw_token.endswith("}"):
            try:
                parsed_json = json.loads(raw_token)
                if isinstance(parsed_json, dict):
                    config.update(parsed_json)
                    return config
            except Exception:
                pass

        # Simple string fallback: treat as bearer token or basic auth
        if config["auth_type"] == "bearer":
            config["token"] = raw_token
        elif config["auth_type"] == "api_key":
            config["api_key_value"] = raw_token
        elif config["auth_type"] == "basic":
            config["basic_pass"] = raw_token
            config["basic_user"] = username_email or ""

        return config

    @staticmethod
    def get_credentials(project_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Resolves stored Custom API credentials for a given project.
        """
        import db
        from models.integration_setting import IntegrationSetting

        if not db.db_session:
            return {}

        try:
            query = db.db_session.query(IntegrationSetting).filter_by(provider='custom_api')
            if project_id:
                setting = query.filter_by(project_id=project_id, is_connected=True).first()
                if not setting:
                    # Also try non-connected if just inspecting config
                    setting = query.filter_by(project_id=project_id).first()
            else:
                setting = query.filter_by(is_connected=True).first()

            if setting and setting.base_url:
                cfg = CustomApiTool.parse_config(setting.username_email or "", setting.api_token or "")
                cfg["base_url"] = str(setting.base_url or "").strip()
                cfg["is_connected"] = bool(setting.is_connected)
                cfg["id"] = setting.id
                return cfg
        except Exception as e:
            logger.error(f"[CustomApiTool.get_credentials] Error: {e}")

        return {}

    @classmethod
    def test_connection(cls, project_id: Optional[int] = None, **kwargs) -> Dict[str, Any]:
        """
        Performs a live handshake & data retrieval check against the specified endpoint.
        Returns response latency, status code, and preview payload.
        """
        import db
        from models.integration_setting import IntegrationSetting

        # Load from kwargs or fallback to DB
        endpoint_url = kwargs.get("base_url") or kwargs.get("endpoint_url")
        username_email = kwargs.get("username_email") or ""
        api_token = kwargs.get("api_token") or ""
        custom_config = kwargs.get("custom_config")

        if not endpoint_url and db.db_session and project_id:
            setting = db.db_session.query(IntegrationSetting).filter_by(provider='custom_api', project_id=project_id).first()
            if setting and setting.base_url:
                endpoint_url = setting.base_url
                username_email = setting.username_email or ""
                api_token = setting.api_token or ""

        if not endpoint_url:
            return {
                "success": False,
                "error": "Custom API Endpoint URL is required."
            }

        safe, reason = cls.is_safe_url(endpoint_url)
        if not safe:
            return {
                "success": False,
                "error": f"Security validation failed: {reason}"
            }

        # Resolve config
        cfg = cls.parse_config(username_email, api_token)
        if isinstance(custom_config, dict):
            cfg.update(custom_config)

        method = (kwargs.get("method") or cfg.get("method") or "GET").upper()
        auth_type = (kwargs.get("auth_type") or cfg.get("auth_type") or "bearer").lower()
        token = kwargs.get("token") or cfg.get("token") or ""
        api_key_name = kwargs.get("api_key_name") or cfg.get("api_key_name") or "X-API-Key"
        api_key_value = kwargs.get("api_key_value") or cfg.get("api_key_value") or ""
        basic_user = kwargs.get("basic_user") or cfg.get("basic_user") or ""
        basic_pass = kwargs.get("basic_pass") or cfg.get("basic_pass") or ""
        body_content = kwargs.get("body") or cfg.get("body") or ""

        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "VPM-Enterprise-Governance-Suite/1.0"
        }

        # Merge custom headers
        custom_headers = cfg.get("custom_headers") or kwargs.get("custom_headers") or {}
        if isinstance(custom_headers, str):
            try:
                custom_headers = json.loads(custom_headers)
            except Exception:
                custom_headers = {}
        if isinstance(custom_headers, dict):
            headers.update({str(k): str(v) for k, v in custom_headers.items()})

        # Apply Auth Strategy
        auth = None
        if auth_type == "bearer" and token:
            headers["Authorization"] = f"Bearer {token.strip()}"
        elif auth_type == "api_key" and api_key_value:
            headers[api_key_name.strip()] = api_key_value.strip()
        elif auth_type == "basic":
            auth = HTTPBasicAuth(basic_user, basic_pass)

        # Prepare request payload if POST/PUT
        req_json = None
        req_data = None
        if method in ("POST", "PUT", "PATCH") and body_content:
            if isinstance(body_content, dict):
                req_json = body_content
            elif isinstance(body_content, str) and body_content.strip():
                try:
                    req_json = json.loads(body_content)
                except Exception:
                    req_data = body_content

        start_time = time.perf_counter()
        try:
            resp = requests.request(
                method=method,
                url=endpoint_url.strip(),
                headers=headers,
                auth=auth,
                json=req_json,
                data=req_data,
                timeout=12,
                allow_redirects=True
            )
            elapsed_ms = round((time.perf_counter() - start_time) * 1000)

            parsed_url = urllib.parse.urlparse(endpoint_url)
            server_host = parsed_url.netloc or endpoint_url

            # Try parsing JSON response
            sample_data = None
            try:
                sample_data = resp.json()
            except Exception:
                sample_data = resp.text[:1000]

            if resp.status_code in range(200, 300):
                return {
                    "success": True,
                    "status_code": resp.status_code,
                    "latency_ms": elapsed_ms,
                    "server": server_host,
                    "endpoint": endpoint_url,
                    "method": method,
                    "auth_type": auth_type,
                    "user": f"Authenticated via {auth_type.upper()}" if auth_type != 'none' else "Public Access",
                    "content_type": resp.headers.get("Content-Type", "application/json"),
                    "sample_data": sample_data,
                    "total_bytes": len(resp.content)
                }
            else:
                return {
                    "success": False,
                    "status_code": resp.status_code,
                    "latency_ms": elapsed_ms,
                    "server": server_host,
                    "endpoint": endpoint_url,
                    "error": f"Endpoint returned HTTP {resp.status_code} ({resp.reason or 'Error'}).",
                    "sample_data": sample_data
                }

        except requests.exceptions.Timeout:
            return {
                "success": False,
                "error": "Connection timed out after 12 seconds. Please check the endpoint URL and firewall rules."
            }
        except requests.exceptions.SSLError as ssl_err:
            return {
                "success": False,
                "error": f"SSL / TLS Certificate Handshake failed: {ssl_err}"
            }
        except requests.exceptions.ConnectionError as conn_err:
            return {
                "success": False,
                "error": f"Could not establish connection to host: {conn_err}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Request failed: {str(e)}"
            }

    @classmethod
    def fetch_data(cls, project_id: int) -> Dict[str, Any]:
        """
        Executes live data retrieval from the configured custom API endpoint for a project.
        """
        cfg = cls.get_credentials(project_id=project_id)
        if not cfg or not cfg.get("base_url"):
            return {
                "success": False,
                "error": "No active Custom API endpoint configured for this project."
            }

        res = cls.test_connection(project_id=project_id, **cfg)
        if res.get("success"):
            return {
                "success": True,
                "project_id": project_id,
                "endpoint": cfg.get("base_url"),
                "method": cfg.get("method", "GET"),
                "auth_type": cfg.get("auth_type", "bearer"),
                "data_category": cfg.get("data_category", "general"),
                "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "status_code": res.get("status_code"),
                "latency_ms": res.get("latency_ms"),
                "payload": res.get("sample_data")
            }
        return res
