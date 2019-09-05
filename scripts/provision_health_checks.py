from itertools import chain

import argparse
import boto3
import logging
import json
import sys

import more_itertools

from azul import config
from azul.logging import configure_script_logging

logger = logging.getLogger(__name__)


def main(argv):
    parser = argparse.ArgumentParser(description='Dynamically reference and dereference Route53 child health checks '
                                                 'not managed by Azul.')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--reference', '-R', dest='reference', action='store_true', default=False,
                       help='Link Azul managed Route53 health check resources to DCP wide composite health check.')
    group.add_argument('--dereference', '-D', dest='reference', action='store_false', default=False,
                       help='Unlink Azul managed Route53 health check resources to DCP wide composite health check.')
    options = parser.parse_args(argv)
    health_checks = get_health_checks()
    try:
        dcp_wide_health_check = health_checks[f'dcp-health-check-{config.deployment_stage}']
    except KeyError:
        logger.info(f'DCP wide health check does not exist for {config.deployment_stage}')
    else:
        logger.info('Referencing HealthChecks')
        provision_health_check(health_checks, dcp_wide_health_check, options.reference)


def get_health_checks():
    client, health_checks = health_check_ops()
    health_check_batches = more_itertools.chunked(health_checks, 10)
    dcp_health_checks = {}
    for health_check_batch in health_check_batches:
        health_check_batch = {health_check['Id']: health_check for health_check in health_check_batch}
        response = client.list_tags_for_resources(ResourceType='healthcheck',
                                                  ResourceIds=list(health_check_batch.keys()))
        for tag_sets in response['ResourceTagSets']:
            assert tag_sets['ResourceType'] == 'healthcheck'
            for tag in tag_sets['Tags']:
                if tag['Key'] == 'Name':
                    health_check_name = tag['Value']
                    health_check_id = tag_sets['ResourceId']
                    dcp_health_checks[health_check_name] = health_check_batch[health_check_id]
    return dcp_health_checks


def health_check_ops():
    client = boto3.client('route53')
    paginator = client.get_paginator('list_health_checks')
    return client, chain.from_iterable(page['HealthChecks'] for page in paginator.paginate())


def provision_health_check(health_checks, dcp_health_check, reference):
    dcp_health_check_config = dcp_health_check['HealthCheckConfig']
    azul_service = health_checks[config.service_name]
    azul_indexer = health_checks[config.indexer_name]
    azul_data_browser = health_checks[config.data_browser_name]
    azul_data_portal = health_checks[config.data_portal_name]
    updated_child_health_checks = [health_check for health_check in dcp_health_check_config['ChildHealthChecks']
                                   if health_check not in (azul_service['Id'],
                                                           azul_indexer['Id'],
                                                           azul_data_browser['Id'],
                                                           azul_data_portal['Id'])]
    if reference:
        updated_child_health_checks.append(azul_service['Id'])
        updated_child_health_checks.append(azul_indexer['Id'])
        updated_child_health_checks.append(azul_data_browser['Id'])
        updated_child_health_checks.append(azul_data_portal['Id'])
    response = update_dcp_wide_health_check(dcp_health_check, updated_child_health_checks)
    logger.info(json.dumps(response))


def update_dcp_wide_health_check(dcp_wide_health_check, updated_child_health_checks):
    client = boto3.client('route53')
    dcp_wide_health_check['HealthCheckConfig'].pop('ChildHealthChecks')
    return client.update_health_check(HealthCheckId=dcp_wide_health_check['Id'],
                                      HealthCheckVersion=dcp_wide_health_check['HealthCheckVersion'],
                                      ChildHealthChecks=updated_child_health_checks,
                                      Inverted=dcp_wide_health_check['HealthCheckConfig']['Inverted'],
                                      HealthThreshold=len(updated_child_health_checks))


if __name__ == '__main__':
    configure_script_logging(logger)
    main(sys.argv[1:])
