from handoff.git import changed_files_from_status


def test_unstaged_first_line_keeps_full_path() -> None:
    assert changed_files_from_status(" M utils/features.ts\n?? new.txt") == ["utils/features.ts", "new.txt"]
