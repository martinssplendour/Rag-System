"""Unit tests for filename sanitisation, extension validation, and
path-traversal-safe joining (security checklist section 4/13)."""

import pytest

from app.utils.files import extension_of, is_allowed_extension, safe_join, sanitize_filename


def test_sanitize_filename_strips_directory_components():
    assert sanitize_filename("../../etc/passwd") == "passwd"


def test_sanitize_filename_strips_windows_style_path():
    assert sanitize_filename(r"C:\Windows\System32\evil.txt") == "evil.txt"


def test_sanitize_filename_replaces_unsafe_characters():
    assert sanitize_filename("my file (final)!.txt") == "my_file_final_.txt"


def test_sanitize_filename_handles_empty_and_dot_names():
    assert sanitize_filename("") == "upload"
    assert sanitize_filename(".") == "upload"
    assert sanitize_filename("..") == "upload"


def test_sanitize_filename_truncates_long_names():
    long_name = "a" * 500 + ".txt"
    result = sanitize_filename(long_name)
    assert len(result) <= 200


def test_extension_of_is_case_insensitive():
    assert extension_of("Report.PDF") == ".pdf"


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("summary.txt", True),
        ("summary.pdf", True),
        ("summary.exe", False),
        ("summary", False),
        ("summary.PDF", True),
    ],
)
def test_is_allowed_extension(filename: str, expected: bool):
    assert is_allowed_extension(filename) is expected


def test_safe_join_allows_paths_within_base(tmp_path):
    result = safe_join(tmp_path, "workspace1", "doc1", "file.txt")
    assert result.startswith(str(tmp_path))


def test_safe_join_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError):
        safe_join(tmp_path, "..", "..", "etc", "passwd")


def test_safe_join_rejects_absolute_escape(tmp_path):
    with pytest.raises(ValueError):
        safe_join(tmp_path, "../../../../etc/shadow")
