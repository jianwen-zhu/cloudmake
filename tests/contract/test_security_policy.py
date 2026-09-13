import re

from conftest import PROJECT_ROOT


def test_github_workflows_never_reference_hosted_secrets() -> None:
    workflow_root = PROJECT_ROOT / ".github" / "workflows"
    workflows = sorted((*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml")))
    assert workflows

    for workflow in workflows:
        contents = workflow.read_text(encoding="utf-8").lower()
        assert re.search(r"\bsecrets(?:\.|\[)", contents) is None, (
            f"{workflow.name} references a GitHub secret; Cloudmake hosted CI "
            "must remain credential-free"
        )
