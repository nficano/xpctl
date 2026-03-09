from xpctl.resources import read_remote_script


def test_read_remote_script_find():
    source = read_remote_script("find")

    assert 'root = payload["root"]' in source
    assert 'result = {"matches": matches}' in source


def test_read_remote_scripts_all_extracted_variants():
    names = [
        "checksum",
        "dll_inject",
        "file_delete",
        "file_list",
        "file_stat",
        "find",
        "gui_screenshot",
        "gui_sendkeys",
        "gui_window_list",
        "head",
        "mem_read",
        "memdump",
        "run_python_json",
        "run_python_wrapper",
        "tail",
    ]

    for name in names:
        source = read_remote_script(name)
        assert source
