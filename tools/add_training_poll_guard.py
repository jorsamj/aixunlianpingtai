from pathlib import Path

path = Path('.github/workflows/frontend-runtime-stabilization.yml')
text = path.read_text(encoding='utf-8')
marker = """          grep -Fq 'replaceSourceTimer();' \"$file\"\n      - name: Frontend unit tests\n"""
if text.count(marker) != 1:
    raise SystemExit(f'expected one insertion marker, found {text.count(marker)}')
block = """          grep -Fq 'replaceSourceTimer();' \"$file\"\n      - name: Training PollRegistry direct owner guard\n        run: |\n          for file in static/app.js static/modules/poll-registry.js static/modules/navigation-stability.js; do\n            if grep -F -n 'jobPollTimer' \"$file\"; then\n              echo \"retired training polling state timer was reintroduced into $file\" >&2\n              exit 1\n            fi\n          done\n          if grep -Fq 'setupPagePolling' static/app.js; then\n            if ! grep -Fq 'window.PollRegistryRuntime?.replaceTrainingJobTimer?.();' static/app.js; then\n              echo 'remaining setupPagePolling entrypoints must hand lifecycle explicitly to PollRegistry' >&2\n              exit 1\n            fi\n          fi\n          file=static/modules/poll-registry.js\n          for token in \\\n            installPollingCreationBridge \\\n            __pollRegistryCreationWrapped \\\n            originalSetupPagePolling \\\n            wrappedSetupPagePolling \\\n            \"registry.adopt('training-jobs'\" \\\n            adoptLegacy \\\n            rebindCreation; do\n            if grep -F -n \"$token\" \"$file\"; then\n              echo \"training polling wrapper/adoption compatibility was reintroduced: $token\" >&2\n              exit 1\n            fi\n          done\n          grep -Fq 'replaceTrainingJobTimer,' \"$file\"\n          grep -Fq 'replaceTrainingJobTimer();' \"$file\"\n      - name: Frontend unit tests\n"""
path.write_text(text.replace(marker, block, 1), encoding='utf-8')
print('added permanent Training PollRegistry direct owner guard')
