from azul import config
from azul.deployment import aws
from azul.template import emit

suffix = '-' + config.deployment_stage
assert config.service_name.endswith(suffix)

emit({
    'version': '2.0',
    'app_name': config.service_name[:-len(suffix)],  # Chalice appends stage name implicitly
    'api_gateway_stage': config.deployment_stage,
    'manage_iam_role': False,
    'iam_role_arn': f'arn:aws:iam::{aws.account}:role/{config.service_name}',
    'environment_variables': aws.lambda_env(config.service_name),
    'lambda_timeout': config.api_gateway_timeout + config.api_gateway_timeout_padding,
    'lambda_memory_size': 1024,
    'stages': {
        config.deployment_stage: {
            'lambda_functions': {
                config.manifest_lambda_basename: {
                    'lambda_timeout': config.service_lambda_timeout
                },
                config.cart_item_write_lambda_basename: {
                    'lambda_timeout': config.service_lambda_timeout
                },
                config.cart_export_dss_push_lambda_basename: {
                    'lambda_timeout': config.service_lambda_timeout
                }
            }
        }
    }
})
