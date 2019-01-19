import json

from azul import config
from azul.template import emit


def cart_item_states():
    return {
        "WriteBatch": {
            "Type": "Task",
            "Resource": config.get_lambda_arn(config.service_name, config.cart_item_write_lambda_basename),
            "Next": "NextBatch",
            "ResultPath": "$.write_result"
        },
        "NextBatch": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.write_result.count",
                    "NumericEquals": 0,
                    "Next": "SuccessState"
                }
            ],
            "Default": "WriteBatch"
        },
        "SuccessState": {
            "Type": "Succeed"
        }
    }


emit({
    "resource": {
        "aws_iam_role": {
            "state_machine_iam_role": {
                "name": config.qualified_resource_name("statemachine"),
                "assume_role_policy": json.dumps({
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Sid": "",
                            "Effect": "Allow",
                            "Principal": {
                                "Service": "states.amazonaws.com"
                            },
                            "Action": "sts:AssumeRole"
                        }
                    ]
                })
            }
        },
        "aws_iam_role_policy": {
            "state_machine_iam_policy": {
                "name": config.qualified_resource_name("statemachine"),
                "role": "${aws_iam_role.state_machine_iam_role.id}",
                "policy": json.dumps({
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": [
                                "lambda:InvokeFunction"
                            ],
                            "Resource": [
                                config.get_lambda_arn(config.service_name, config.manifest_lambda_basename),
                                config.get_lambda_arn(config.service_name, config.cart_item_write_lambda_basename)
                            ]
                        }
                    ]
                })
            }
        },
        "aws_sfn_state_machine": {
            "manifest_state_machine": {
                "name": config.manifest_state_machine_name,
                "role_arn": "${aws_iam_role.state_machine_iam_role.arn}",
                "definition": json.dumps({
                    "StartAt": "WriteManifest",
                    "States": {
                        "WriteManifest": {
                            "Type": "Task",
                            "Resource": config.get_lambda_arn(config.service_name, config.manifest_lambda_basename),
                            "End": True
                        }
                    }
                }, indent=2)
            },
            "cart_item_state_machine": {
                "name": config.cart_item_state_machine_name,
                "role_arn": "${aws_iam_role.state_machine_iam_role.arn}",
                "definition": json.dumps({
                    "StartAt": "WriteBatch",
                    "States": cart_item_states()
                }, indent=2)
            }
        }
    }
})