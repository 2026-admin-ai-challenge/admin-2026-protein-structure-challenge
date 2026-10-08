from app.diagnostics import failure_detail


def test_missing_library_identifies_package_and_last_entrypoint_line():
    log = '''Traceback (most recent call last):
  File "/submission/inference.py", line 39, in <module>
    main()
  File "/submission/inference.py", line 25, in main
    bundle = joblib.load(MODEL_PATH)
ModuleNotFoundError: No module named 'catboost'
'''
    detail = failure_detail("runtime_error", log)
    assert "catboost" in detail and "inference.py 25행" in detail
    assert "requirements.txt" in detail and "해결 방법:" in detail
    assert "bundle" not in detail and "MODEL_PATH" not in detail


def test_untrusted_values_and_paths_never_reach_participants():
    for last in ["ModuleNotFoundError: No module named 'SECRET_LABEL'", "FileNotFoundError: /input/SECRET_ID", "ValueError: SECRET_LABEL"]:
        detail = failure_detail("runtime_error", 'File "/submission/SECRET_ID.py", line 12,\n' + last)
        assert detail and "SECRET" not in detail


def test_arbitrary_output_and_server_faults_are_not_exposed():
    assert failure_detail("runtime_error", "secret stdout\nSomethingSecretError: SECRET") is None
    assert failure_detail("system_error", "ModuleNotFoundError: No module named 'catboost'") is None
    assert failure_detail("runtime_error", None) is None


def test_earlier_stdout_is_not_mistaken_for_final_exception():
    detail = failure_detail("runtime_error", "ModuleNotFoundError: No module named 'catboost'\nValueError: SECRET")
    assert "ValueError" in detail and "catboost" not in detail and "SECRET" not in detail
