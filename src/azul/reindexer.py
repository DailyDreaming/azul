#! /usr/bin/env python3

from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
import json
import logging
from pprint import PrettyPrinter
from urllib.error import HTTPError
from urllib.parse import urlparse, urlencode, parse_qs
from urllib.request import Request, urlopen
from uuid import uuid4

from azul import config

logger = logging.getLogger(__name__)

plugin = config.plugin()


class Defaults:
    dss_url = config.dss_endpoint
    indexer_url = "https://" + config.api_lambda_domain('indexer') + "/"
    es_query = plugin.dss_subscription_query
    num_workers = 16


class Reindexer(object):
    def __init__(self, indexer_url: str = Defaults.indexer_url,
                 dss_url: str = Defaults.dss_url,
                 es_query: dict = Defaults.es_query,
                 sync: bool = False,
                 num_workers: int = Defaults.num_workers,
                 test_name: str = None,
                 dryrun: bool = None):

        self.num_workers = num_workers
        self.sync = sync
        self.es_query = es_query
        self.dss_url = dss_url
        self.indexer_url = indexer_url
        self.test_name = test_name
        self.dryrun = dryrun

    def post_bundle(self, bundle_fqid, es_query, indexer_url):
        """
        Send a mock DSS notification to the indexer
        """
        bundle_uuid, _, bundle_version = bundle_fqid.partition('.')
        simulated_event = {
            "query": es_query,
            "subscription_id": str(uuid4()),
            "transaction_id": str(uuid4()),
            "match": {
                "bundle_uuid": bundle_uuid,
                "bundle_version": bundle_version
            }
        }
        body = json.dumps(simulated_event).encode('utf-8')
        request = Request(indexer_url, body)
        request.add_header("content-type", "application/json")
        with urlopen(request) as f:
            return f.read()

    def reindex(self):
        errors = defaultdict(int)
        missing = {}
        indexed = 0
        total = 0

        logger.info('Querying DSS using %s', json.dumps(self.es_query, indent=4))
        dss_client = config.dss_client(dss_endpoint=self.dss_url)
        # noinspection PyUnresolvedReferences
        response = dss_client.post_search.iterate(es_query=self.es_query, replica="aws")
        bundle_fqids = [r['bundle_fqid'] for r in response]
        logger.info("Bundle FQIDs to index: %i", len(bundle_fqids))

        with ThreadPoolExecutor(max_workers=self.num_workers, thread_name_prefix='pool') as tpe:

            def attempt(bundle_fqid, i):
                try:
                    logger.info("Bundle %s, attempt %i: Sending notification", bundle_fqid, i)
                    url = urlparse(self.indexer_url)
                    if self.sync is not None:
                        # noinspection PyProtectedMember
                        url = url._replace(query=urlencode({**parse_qs(url.query),
                                                            'sync': self.sync}, doseq=True))
                    if not self.dryrun:
                        self.post_bundle(bundle_fqid=bundle_fqid,
                                         es_query=self.es_query,
                                         indexer_url=url.geturl())
                except HTTPError as e:
                    if i < 3:
                        logger.warning("Bundle %s, attempt %i: scheduling retry after error %s", bundle_fqid, i, e)
                        return bundle_fqid, tpe.submit(partial(attempt, bundle_fqid, i + 1))
                    else:
                        logger.warning("Bundle %s, attempt %i: giving up after error %s", bundle_fqid, i, e)
                        return bundle_fqid, e
                else:
                    logger.info("Bundle %s, attempt %i: success", bundle_fqid, i)
                    return bundle_fqid, None

            def handle_future(future):
                nonlocal indexed
                # Block until future raises or succeeds
                exception = future.exception()
                if exception is None:
                    bundle_fqid, result = future.result()
                    if result is None:
                        indexed += 1
                    elif isinstance(result, HTTPError):
                        errors[result.code] += 1
                        missing[bundle_fqid] = result.code
                    elif isinstance(result, Future):
                        # The task scheduled a follow-on task, presumably a retry. Follow that new task.
                        handle_future(result)
                    else:
                        assert False
                else:
                    logger.warning("Unhandled exception in worker:", exc_info=exception)

            futures = []
            for bundle_fqid in bundle_fqids:
                total += 1
                futures.append(tpe.submit(partial(attempt, bundle_fqid, 0)))
            for future in futures:
                handle_future(future)
        printer = PrettyPrinter(stream=None, indent=1, width=80, depth=None, compact=False)
        logger.info("Total of bundle FQIDs read: %i", total)
        logger.info("Total of bundle FQIDs indexed: %i", indexed)
        logger.warning("Total number of errors by code:\n%s", printer.pformat(dict(errors)))
        logger.warning("Missing bundle_fqids and their error code:\n%s", printer.pformat(missing))