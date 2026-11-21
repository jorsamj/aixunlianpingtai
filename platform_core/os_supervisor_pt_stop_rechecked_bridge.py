"""2C-03C2: CI-only CENTRAL-signed STOP -> root CAS -> original OS observer.

Never exposed as an Agent or production service interface. No result upload,
StopReceipt, trusted recovery, central resource release or process relaunch.
The exact original central STOP grant must already be consumed in the SAME
root-owned ExecutionJournal before this bridge can call systemd.
"""
from __future__ import annotations

import os

from .os_supervisor_authorization import GrantRejected
from .os_supervisor_pt_export_launch import PtExportJournal
from .os_supervisor_pt_stop_observation import IsolatedPtStopObserver


class CiOnlyPtStopRecheckedBridge:
    """One OS stop observation per original centrally authorized invocation."""

    def __init__(
        self, journal: PtExportJournal, observer: IsolatedPtStopObserver,
        *, isolated_ci_only: bool = False,
    ):
        if (isolated_ci_only is not True
                or type(journal) is not PtExportJournal
                or type(observer) is not IsolatedPtStopObserver
                or observer.journal is not journal
                or os.name != "posix" or os.geteuid() != 0
                or os.environ.get("GITHUB_ACTIONS") != "true"
                or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
                or journal.journal.test_only_unprivileged is not True):
            raise GrantRejected("PT_STOP_BRIDGE_PRODUCTION_DISABLED_HOLD")
        self.journal = journal
        self.observer = observer

    def stop_original_after_central_cas(
        self, handle_id: str, task_attempt: int,
    ) -> dict:
        """Consume OS probe CAS first; no retries after uncertain stop.

        No OS inspection or stop is even attempted without a signed central
        STOP grant already atomically claimed for this original invocation.
        """
        reserved = self.journal.claim_pt_os_stop_observation(
            handle_id, task_attempt,
        )
        observed = self.observer.request_and_observe(handle_id, task_attempt)
        if (observed.get("original_unit") != reserved["unit_name"]
                or observed.get("original_invocation_id")
                != reserved["invocation_id"]
                or observed.get("original_main_pid") != reserved["main_pid"]
                or observed.get("central_recovery_allowed") is not False
                or observed.get("trusted_stop_receipt_available") is not False):
            raise GrantRejected("PT_STOP_BRIDGE_RESULT_IDENTITY_UNVERIFIED_HOLD")
        return {
            **observed,
            "stop_grant_digest": reserved["stop_grant_digest"],
            "os_probe_claimed_once": True,
            "trusted_stop_receipt_available": False,
            "central_recovery_allowed": False,
            "result_publish_allowed": False,
            "production_launch_allowed": False,
        }
