def test_all_error_codes_in_catalog():
    from errors.codes import ErrorCode, ERROR_CATALOG
    missing = [code for code in ErrorCode if code not in ERROR_CATALOG]
    assert missing == [], f"ErrorCodes missing from ERROR_CATALOG: {missing}"

def test_catalog_entries_have_all_fields():
    from errors.codes import ERROR_CATALOG
    for code, info in ERROR_CATALOG.items():
        assert isinstance(info.http_status, int), f"{code}: http_status not int"
        assert isinstance(info.user_hint, str) and info.user_hint, f"{code}: user_hint empty"
        assert isinstance(info.retryable, bool), f"{code}: retryable not bool"
        assert isinstance(info.details_template, str), f"{code}: details_template not str"

def test_merged_codes_not_duplicated():
    from errors.codes import ErrorCode
    values = [e.value for e in ErrorCode]
    assert len(values) == len(set(values)), "Duplicate ErrorCode values detected"

def test_retryable_field_is_bool_for_all_codes():
    from errors.codes import ERROR_CATALOG
    for code, info in ERROR_CATALOG.items():
        assert isinstance(info.retryable, bool), f"{code}.retryable is not bool"

def test_job_timeout_and_unsupported_file_type_not_duplicated():
    from errors.codes import ErrorCode
    values = [e.value for e in ErrorCode]
    assert values.count("JOB_TIMEOUT") == 1
    assert values.count("UNSUPPORTED_FILE_TYPE") == 1
