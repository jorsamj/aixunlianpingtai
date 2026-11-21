"""Generic Agent/transport must not import the training stack for scenario checks."""
import subprocess
import sys


def test_generic_scenario_verifier_stays_available_without_training_dependencies():
    source = r"""
import importlib.abc
import sys
from types import SimpleNamespace
class NoTraining(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'yaml', 'platform_core.training_tasks'}:
            raise ImportError('generic transport must not load training dependency: ' + fullname)
sys.meta_path.insert(0, NoTraining())
from platform_core.scenario_models import verify_scenario_request
verify_scenario_request(SimpleNamespace(task=SimpleNamespace(payload_ref='request.json')), {})
assert 'platform_core.training_tasks' not in sys.modules
assert 'yaml' not in sys.modules
"""
    result = subprocess.run([sys.executable, '-c', source], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
