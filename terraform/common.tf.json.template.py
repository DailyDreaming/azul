import os

from azul import config, require
from azul.template import emit

expected_component_path = os.path.join(os.path.abspath(config.project_root), 'terraform', config.terraform_component)
actual_component_path = os.path.dirname(os.path.abspath(__file__))
require(os.path.samefile(expected_component_path, actual_component_path),
        f"The current Terraform component is set to '{config.terraform_component}'. "
        f"You should therefore be in '{expected_component_path}'")

emit({
    "data": [
        {
            "aws_caller_identity": {
                "current": {}
            }
        },
        {
            "aws_region": {
                "current": {}
            }
        },
        *([{
            "google_client_config": {
                "current": {}
            }
        }] if config.enable_gcp() else [])
    ],
    "locals": {
        "account_id": "${data.aws_caller_identity.current.account_id}",
        "region": "${data.aws_region.current.name}",
        "google_project": "${data.google_client_config.current.project}" if config.enable_gcp() else None
    }
})
