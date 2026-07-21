from agent.model_policy import enforce_model_policy, is_nvidia_model


def test_blocks_openrouter_nvidia_models():
    assert is_nvidia_model("nvidia/nemotron-3-super-120b-a12b:free")
    assert enforce_model_policy("nvidia/other-model:free") == ""


def test_blocks_direct_nvidia_provider_and_endpoint():
    assert is_nvidia_model("nemotron", "nvidia")
    assert is_nvidia_model("custom-model", base_url="https://integrate.api.nvidia.com/v1")


def test_keeps_non_nvidia_model():
    assert not is_nvidia_model("deepseek/deepseek-v4-flash", "openrouter")
    assert enforce_model_policy("deepseek/deepseek-v4-flash", "openrouter") == "deepseek/deepseek-v4-flash"