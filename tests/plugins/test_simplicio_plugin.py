from plugins.simplicio import _on_pre_tool_call


def test_blocks_native_write_inside_managed_repo():
    result = _on_pre_tool_call(
        tool_name="write_file",
        args={"path": "/Users/wesleysimplicio/Projetos/ai/simplicio-runtime/src/main.rs", "content": "x"},
    )
    assert isinstance(result, dict)
    assert result["action"] == "block"
    assert "simplicio-runtime" in result["message"]
    assert "simplicio edit" in result["message"]


def test_allows_native_write_outside_managed_repo():
    result = _on_pre_tool_call(
        tool_name="write_file",
        args={"path": "/tmp/example.txt", "content": "x"},
    )
    assert result is None
