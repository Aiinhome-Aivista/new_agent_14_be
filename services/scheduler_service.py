import threading
import time
import logging
from datetime import datetime, timezone
import os

logger = logging.getLogger(__name__)

class SchedulerService:
    _instance = None
    _lock = threading.Lock()

    def __init__(self, app=None, interval_seconds: int = 3600):
        self.app = app
        self.interval_seconds = interval_seconds
        self.is_running = False
        self.last_run = None
        self.last_status = "idle"
        self.last_error = None
        self.sync_count = 0
        self._thread = None
        self._stop_event = threading.Event()

    @classmethod
    def get_instance(cls, app=None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(app=app)
            elif app is not None and cls._instance.app is None:
                cls._instance.app = app
            return cls._instance

    def start(self):
        if self.is_running:
            logger.info("Scheduler already running.")
            return

        # Werkzeug reloader guard in debug mode: only run in main worker
        if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
            logger.info("Skipping scheduler in Werkzeug watcher process.")
            return

        self.is_running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="VPMSchedulerThread")
        self._thread.start()
        logger.info(f"Background Sync Scheduler started (interval={self.interval_seconds}s).")

    def stop(self):
        if not self.is_running:
            return
        self.is_running = False
        self._stop_event.set()
        logger.info("Background Sync Scheduler stopping.")

    def _run_loop(self):
        # Initial wait of 30 seconds after server launch before first background sweep
        if self._stop_event.wait(timeout=30):
            return

        while self.is_running and not self._stop_event.is_set():
            try:
                self._execute_sync_cycle()
            except Exception as e:
                logger.error(f"Error in scheduler sync cycle: {e}", exc_info=True)
                self.last_status = "error"
                self.last_error = str(e)

            # Wait for interval or stop event
            if self._stop_event.wait(timeout=self.interval_seconds):
                break

    def trigger_sync_now(self):
        """Allows manual triggering of the sync cycle asynchronously."""
        t = threading.Thread(target=self._execute_sync_cycle, daemon=True)
        t.start()
        return {"status": "triggered", "message": "Manual synchronization triggered in background."}

    def _execute_sync_cycle(self):
        logger.info("Executing scheduled synchronization cycle across enterprise connectors...")
        self.last_status = "syncing"
        self.last_run = datetime.now(timezone.utc).isoformat()
        
        results = {
            "jira": None,
            "azure_devops": None,
            "sap_erp": None,
            "sharepoint": None,
            "timestamp": self.last_run
        }

        try:
            # We import tools lazily to avoid circular dependencies
            from tools.jira_tool import JiraTool
            from tools.azure_devops_tool import AzureDevOpsTool
            from tools.sap_erp_tool import SapErpTool
            from tools.sharepoint_tool import SharepointTool
            import db
            from models.dashboard_snapshot import DashboardSnapshot

            from models.integration_setting import IntegrationSetting

            # Fetch settings to check if they are explicitly connected via UI
            settings_map = {}
            if db.db_session:
                all_settings = db.db_session.query(IntegrationSetting).all()
                for s in all_settings:
                    settings_map[s.provider] = s

            # 1. Jira Connector Check
            try:
                jira_setting = settings_map.get("jira")
                if jira_setting and jira_setting.is_connected:
                    results["jira"] = JiraTool.test_connection()
                    if results["jira"].get("success"):
                        # Also sync projects and programs to db
                        sync_res = JiraTool.sync_projects_to_db()
                        logger.info(f"Jira Project Sync Result: {sync_res}")
                else:
                    results["jira"] = {"success": False, "error": "Connector not enabled or disconnected in UI"}
            except Exception as e:
                results["jira"] = {"success": False, "error": str(e)}

            # 2. Azure DevOps Connector Check
            try:
                ado_setting = settings_map.get("azure_devops")
                if ado_setting and ado_setting.is_connected:
                    results["azure_devops"] = AzureDevOpsTool.test_connection()
                    if results["azure_devops"].get("success"):
                        sync_res = AzureDevOpsTool.sync_projects_to_db()
                        logger.info(f"Azure DevOps Project Sync Result: {sync_res}")
                else:
                    results["azure_devops"] = {"success": False, "error": "Connector not enabled or disconnected in UI"}
            except Exception as e:
                results["azure_devops"] = {"success": False, "error": str(e)}

            # 3. SAP ERP Connector Check
            try:
                sap_setting = settings_map.get("sap_erp")
                if sap_setting and sap_setting.is_connected:
                    results["sap_erp"] = SapErpTool.test_connection()
                    if results["sap_erp"].get("success"):
                        sync_res = SapErpTool.sync_projects_to_db()
                        logger.info(f"SAP ERP Cost Center Sync Result: {sync_res}")
                else:
                    results["sap_erp"] = {"success": False, "error": "Connector not enabled or disconnected in UI"}
            except Exception as e:
                results["sap_erp"] = {"success": False, "error": str(e)}

            # 4. SharePoint Connector Check
            try:
                sp_setting = settings_map.get("sharepoint")
                if sp_setting and sp_setting.is_connected:
                    results["sharepoint"] = SharepointTool.test_connection()
                    if results["sharepoint"].get("success"):
                        sync_res = SharepointTool.sync_projects_to_db()
                        logger.info(f"SharePoint Document Library Sync Result: {sync_res}")
                else:
                    results["sharepoint"] = {"success": False, "error": "Connector not enabled or disconnected in UI"}
            except Exception as e:
                results["sharepoint"] = {"success": False, "error": str(e)}

            # 5. Refresh latest dashboard snapshot with connector sync status if db_session available
            if db.db_session:
                try:
                    latest_snapshot = db.db_session.query(DashboardSnapshot).order_by(DashboardSnapshot.id.desc()).first()
                    if latest_snapshot and isinstance(latest_snapshot.data, dict):
                        # Create updated shallow copy to trigger SQLAlchemy change tracking
                        updated_data = dict(latest_snapshot.data)
                        updated_data["last_scheduler_sync"] = self.last_run
                        updated_data["connectors_health"] = {
                            k: (v.get("success", False) if isinstance(v, dict) else False)
                            for k, v in results.items() if k != "timestamp"
                        }
                        latest_snapshot.data = updated_data
                        db.db_session.commit()
                except Exception as db_err:
                    logger.warning(f"Scheduler snapshot update warning: {db_err}")
                    if db.db_session:
                        db.db_session.rollback()
                finally:
                    if db.db_session:
                        db.db_session.remove()

            self.sync_count += 1
            self.last_status = "success"
            self.last_error = None
            logger.info(f"Scheduled sync cycle #{self.sync_count} completed successfully.")
        except Exception as e:
            self.last_status = "failed"
            self.last_error = str(e)
            logger.error(f"Scheduled sync cycle failed: {e}")

    def get_status(self):
        return {
            "is_running": self.is_running,
            "interval_seconds": self.interval_seconds,
            "sync_count": self.sync_count,
            "last_run": self.last_run,
            "last_status": self.last_status,
            "last_error": self.last_error
        }
