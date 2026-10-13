# Publication validation

Checked on 2026-10-13. These results apply to the publication copy, not every historical snapshot.

Final router suite: **311 passed, 2 failed, 1 skipped, 15 subtests passed** on Windows/Python 3.14. The two remaining failures are:

- `core_service_test.py::RouterServiceTests::test_partial_finished_output_retry_only_recopies_third_worker_preserving_accepted_recipe`: observed worker-call order differs from the asserted order.
- `test_llm.py::LLMTests::test_recursive_json_reply_records_safe_failure_and_preserves_original_prompt`: returned failure category is `invalid_task_fields`, while the test expects `malformed_json`.

Publication-related fixture and source-integrity checks pass after retaining the sanitized original notebook fixture and required embedded-source checksums. The Python test environment used aiohttp 3.14.5 rather than the runtime requirements’ 3.14.3; GPU/Linux/Android results cannot be inferred from these Windows checks. No Colab runtime, model download or physical Android build was exercised.

## Publication checks

Source files and retained history are scanned for credentials with Gitleaks and additional manual review of configuration, notebooks and private data. A specific upstream SHA-256 in Phone Studio is allowlisted as an integrity checksum, not a credential. This is a bounded review, not a guarantee that the projects are defect-free. Large runtime files, secrets and local account/session databases are excluded.
