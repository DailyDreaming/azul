import os
import git

from azul import config
from azul.deployment import aws
from azul.template import emit

suffix = '-' + config.deployment_stage
assert config.service_name.endswith(suffix)

host, port = config.es_endpoint
repo = git.Repo(config.project_root)

emit({
    'version': '2.0',
    'app_name': config.service_name[:-len(suffix)],  # Chalice appends stage name implicitly
    'api_gateway_stage': config.deployment_stage,
    'manage_iam_role': False,
    'iam_role_arn': f'arn:aws:iam::{aws.account}:role/{config.service_name}',
    'environment_variables': {
        **{k: v for k, v in os.environ.items() if k.startswith('AZUL_') and k != 'AZUL_HOME'},
        # Hard-wire the ES endpoint, so we don't need to look it up at run-time, for every request/invocation
        'AZUL_ES_ENDPOINT': f'{host}:{port}',
        'azul_git_commit': repo.head.object.hexsha,
        'azul_git_dirty': str(repo.is_dirty()),
        'HOME': '/tmp'
    },
    'lambda_timeout': 31,
    'lambda_memory_size': 1024
})
