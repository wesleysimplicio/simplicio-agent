from plugins.simplicio import _on_pre_tool_call


def test_does_not_block_native_write_before_runtime_adapter():
    result = _on_pre_tool_call(
        tool_name="write_file",
        args={"path": "/Users/wesleysimplicio/Projetos/ai/simplicio-runtime/src/main.rs", "content": "x"},
    )
    assert result is None


def test_allows_native_write_outside_managed_repo():
    result = _on_pre_tool_call(
        tool_name="write_file",
        args={"path": "/tmp/example.txt", "content": "x"},
    )
    assert result is None
