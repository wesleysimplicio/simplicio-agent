from agent.model_policy import DEFAULT_MODEL, enforce_model_policy, is_nvidia_model


def test_blocks_openrouter_nvidia_models():
    assert is_nvidia_model("nvidia/nemotron-3-super-120b-a12b:free")
    assert enforce_model_policy("nvidia/other-model:free") == DEFAULT_MODEL


def test_blocks_direct_nvidia_provider_and_endpoint():
    assert is_nvidia_model("nemotron", "nvidia")
    assert is_nvidia_model("custom-model", base_url="https://integrate.api.nvidia.com/v1")


def test_keeps_default_tencent_model():
    assert not is_nvidia_model(DEFAULT_MODEL, "openrouter")
    assert enforce_model_policy(DEFAULT_MODEL, "openrouter") == DEFAULT_MODEL
