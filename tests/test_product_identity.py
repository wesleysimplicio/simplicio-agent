"""Canonical ProductIdentity contract for GitHub issue #186."""

from hermes_constants import CANONICAL_CLI_NAME
from simplicio_agent.product_identity import PRODUCT_IDENTITY
from tools.machine_contracts import make_product_identity


def test_product_identity_names_every_canonical_surface() -> None:
    assert PRODUCT_IDENTITY.product == "Simplicio Agent"
    assert PRODUCT_IDENTITY.cli == "simplicio-agent"
    assert PRODUCT_IDENTITY.distribution == PRODUCT_IDENTITY.cli
    assert PRODUCT_IDENTITY.python_namespace == "simplicio_agent"
    assert PRODUCT_IDENTITY.environment_prefix == "SIMPLICIO_AGENT_"
    assert PRODUCT_IDENTITY.state_root == "~/.simplicio/agent"
    assert PRODUCT_IDENTITY.protocol_prefix == "simplicio.agent."
    assert PRODUCT_IDENTITY.kernel == "simplicio"


def test_existing_identity_contract_projects_the_canonical_source() -> None:
    contract = make_product_identity("1.2.3")

    assert contract.product == PRODUCT_IDENTITY.product
    assert contract.surface == PRODUCT_IDENTITY.cli
    assert CANONICAL_CLI_NAME == PRODUCT_IDENTITY.cli
