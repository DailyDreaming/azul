from utils import config, aws
from utils.template import emit

gateway_ids = {
    lambda_name: aws.api_gateway_id(config.resource_name(lambda_name))
    for lambda_name in ('service', 'indexer')
}

emit({
    "data": [
        {
            "aws_route53_zone": {
                "azul": {
                    "name": config.domain_name + ".",
                    "private_zone": False
                }
            }
        }
    ],
    "resource": [
        {
            "aws_api_gateway_deployment": {
                lambda_name: {
                    "rest_api_id": gateway_id,
                    "stage_name": config.deployment_stage
                }
            },
            "aws_api_gateway_base_path_mapping": {
                lambda_name: {
                    "api_id": gateway_id,
                    "stage_name": "${aws_api_gateway_deployment.%s.stage_name}" % lambda_name,
                    "domain_name": "${aws_api_gateway_domain_name.%s.domain_name}" % lambda_name
                }
            },
            "aws_api_gateway_domain_name": {
                lambda_name: {
                    "domain_name": "${aws_acm_certificate.%s.domain_name}" % lambda_name,
                    "certificate_arn": "${aws_acm_certificate_validation.%s.certificate_arn}" % lambda_name
                }
            },
            "aws_acm_certificate": {
                lambda_name: {
                    "domain_name": config.subdomain(lambda_name) + "." + config.domain_name,
                    "validation_method": "DNS",
                }
            },
            "aws_acm_certificate_validation": {
                lambda_name: {
                    "certificate_arn": "${aws_acm_certificate.%s.arn}" % lambda_name,
                    "validation_record_fqdns": ["${aws_route53_record.%s_domain_validation.fqdn}" % lambda_name]
                }
            },
            "aws_route53_record": {
                lambda_name + "_domain_validation": {
                    "name": "${aws_acm_certificate.%s.domain_validation_options.0.resource_record_name}" % lambda_name,
                    "type": "${aws_acm_certificate.%s.domain_validation_options.0.resource_record_type}" % lambda_name,
                    "zone_id": "${data.aws_route53_zone.azul.id}",
                    "records": [
                        "${aws_acm_certificate.%s.domain_validation_options.0.resource_record_value}" % lambda_name],
                    "ttl": 60
                },
                lambda_name: {
                    "zone_id": "${data.aws_route53_zone.azul.zone_id}",
                    "name": "${aws_api_gateway_domain_name.%s.domain_name}" % lambda_name,
                    "type": "A",
                    "alias": {
                        "name": "${aws_api_gateway_domain_name.%s.cloudfront_domain_name}" % lambda_name,
                        "zone_id": "${aws_api_gateway_domain_name.%s.cloudfront_zone_id}" % lambda_name,
                        "evaluate_target_health": True,
                    }
                }
            }
        } for lambda_name, gateway_id in gateway_ids.items() if gateway_id
    ]
})
