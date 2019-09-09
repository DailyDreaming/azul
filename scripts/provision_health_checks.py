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


class ProvisionHealthChecks:

    def __init__(self):
        self.client = boto3.client('route53')

    def main(self, argv):
        parser = argparse.ArgumentParser(
            description='Dynamically reference or dereference Azul\'s Route53 health checks '
                        'to/from composite health checkers not managed by Azul.')
        group = parser.add_mutually_exclusive_group()
        group.add_argument('--reference', '-R', dest='reference', action='store_true', default=False,
                           help='Link Azul managed Route53 health check resources to DCP wide composite health check.')
        group.add_argument('--dereference', '-D', dest='reference', action='store_false', default=False,
                           help='Unlink Azul managed Route53 health check resources to DCP wide composite health '
                                'check.')
        options = parser.parse_args(argv)
        health_checks = self.get_health_checks
        try:
            dcp_wide_health_check = health_checks[f'dcp-health-check-{config.deployment_stage}']
        except KeyError:
            logger.info(f'DCP wide health check does not exist for {config.deployment_stage}')
        else:
            self.provision_health_check(health_checks, dcp_wide_health_check, options.reference)

    @property
    def get_health_checks(self):
        paginator = self.client.get_paginator('list_health_checks')
        health_checks = chain.from_iterable(page['HealthChecks'] for page in paginator.paginate())
        health_check_batches = more_itertools.chunked(health_checks, 10)
        dcp_health_checks = {}
        for health_check_batch in health_check_batches:
            health_check_batch = {health_check['Id']: health_check for health_check in health_check_batch}
            response = self.client.list_tags_for_resources(ResourceType='healthcheck',
                                                           ResourceIds=list(health_check_batch.keys()))
            for tag_sets in response['ResourceTagSets']:
                assert tag_sets['ResourceType'] == 'healthcheck'
                for tag in tag_sets['Tags']:
                    if tag['Key'] == 'Name':
                        health_check_name = tag['Value']
                        health_check_id = tag_sets['ResourceId']
                        dcp_health_checks[health_check_name] = health_check_batch[health_check_id]
        return dcp_health_checks

    def provision_health_check(self, health_checks, dcp_health_check, reference):
        dcp_health_check_children = dcp_health_check['HealthCheckConfig']['ChildHealthChecks']
        azul_health_checks = []
        for resource_name in (config.service_name,
                              config.indexer_name,
                              config.data_browser_name,
                              config.data_portal_name):
            try:
                azul_health_checks.append(health_checks[resource_name]['Id'])
            except KeyError:
                logger.info(f'No Azul health checks found for {resource_name}')

        dcp_health_check_children = [health_check for health_check in dcp_health_check_children
                                     if health_check not in azul_health_checks]
        if reference:
            dcp_health_check_children.extend(azul_health_checks)
        response = self.update_dcp_wide_health_check(dcp_health_check, dcp_health_check_children)
        logger.info(json.dumps(response))

    def update_dcp_wide_health_check(self, dcp_wide_health_check, updated_child_health_checks):
        dcp_wide_health_check['HealthCheckConfig'].pop('ChildHealthChecks')
        return self.client.update_health_check(HealthCheckId=dcp_wide_health_check['Id'],
                                               HealthCheckVersion=dcp_wide_health_check['HealthCheckVersion'],
                                               ChildHealthChecks=updated_child_health_checks,
                                               Inverted=dcp_wide_health_check['HealthCheckConfig']['Inverted'],
                                               HealthThreshold=len(updated_child_health_checks))


if __name__ == '__main__':
    configure_script_logging(logger)
    provision_health_checks = ProvisionHealthChecks()
    provision_health_checks.main(sys.argv[1:])
