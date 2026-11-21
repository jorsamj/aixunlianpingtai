"""2C-01 CI-only bridge: unavailable to production and untrusted callers."""
import inspect

import pytest

from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_pt_export_rechecked_bridge import (
    CiOnlyPtExportRecheckedBridge, _FIXED_PARAMS,
)


@pytest.mark.parametrize("opt_in", [False, None, 1, "true"])
def test_bridge_default_off_even_with_forged_inputs(opt_in):
    with pytest.raises(GrantRejected, match="PT_BRIDGE_PRODUCTION_DISABLED_HOLD"):
        CiOnlyPtExportRecheckedBridge(
            object(), object(), object(), isolated_ci_only=opt_in,
        )


def test_bridge_never_owns_central_credentials_or_result_upload():
    # The central signer is a separate object in the integration test.
    # This bridge only consumes a previously signed launch envelope.
    signature = inspect.signature(CiOnlyPtExportRecheckedBridge.start)
    parameters = set(signature.parameters)
    assert parameters == {
        "self", "handle_id", "task_attempt",
        "central_launch_envelope", "trusted_fixture",
    }
    for forbidden in (
        "node_token", "execution_lease_token", "storage_source",
        "source_url", "model_path", "argv", "env", "cwd", "result_upload",
    ):
        assert forbidden not in parameters
    assert _FIXED_PARAMS == {
        "input_size": 32, "batch": 1, "opset": 12,
        "dynamic": False, "simplify": False,
    }
