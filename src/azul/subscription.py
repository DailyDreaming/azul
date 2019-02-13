#! /usr/bin/env python3

import logging

from azul import config
from azul.json_freeze import freeze, thaw
from azul.plugin import Plugin

logger = logging.getLogger(__name__)


def subscribe(dss_client, subscribe=True):
    response = dss_client.get_subscriptions(replica='aws')
    current_subscriptions = freeze(response['subscriptions'])

    if subscribe:
        plugin = Plugin.load()
        base_url = config.indexer_endpoint()
        prefix = config.dss_query_prefix
        new_subscriptions = [freeze(dict(replica='aws', es_query=query, callback_url=base_url + path))
                             for query, path in [(plugin.dss_subscription_query(prefix), '/'),
                                                 (plugin.dss_deletion_subscription_query(prefix), '/delete')]]
    else:
        new_subscriptions = []

    matching_subscriptions = []
    for subscription in current_subscriptions:
        # Note the use of <= to allow for the fact that DSS returns subscriptions with additional attributes, more
        # than were originally supplied. If the subscription returned by DSS is a superset of the subscription we want
        # to create, we can skip the update.
        matching_subscription = next((new_subscription for new_subscription in new_subscriptions
                                      if new_subscription.items() <= subscription.items()), None)
        if matching_subscription:
            logging.info('Already subscribed: %r', thaw(subscription))
            matching_subscriptions.append(matching_subscription)
        else:
            logging.info('Removing subscription: %r', thaw(subscription))
            dss_client.delete_subscription(uuid=subscription['uuid'], replica=subscription['replica'])

    for subscription in new_subscriptions:
        if subscription not in matching_subscriptions:
            subscription = thaw(subscription)
            response = dss_client.put_subscription(**subscription)
            subscription['uuid'] = response['uuid']
            logging.info('Registered subscription %r.', subscription)