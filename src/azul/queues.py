from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import chain
import json
import logging
import os
import time
from typing import Any, Mapping
from urllib.parse import urlparse

import boto3
import more_itertools
from more_itertools import one

from azul import config
from azul.decorators import memoized_property
from azul.files import write_file_atomically
from azul.lambdas import Lambdas

logger = logging.getLogger(__name__)

Queue = Any  # place-holder for boto3's SQS queue resource


class Queues:

    def __init__(self, delete=False, json_body=True):
        self._delete = delete
        self._json_body = json_body

    def list(self):
        logger.info('Listing queues')
        print('\n{:<35s}{:^20s}{:^20s}{:^18s}\n'.format('Queue Name',
                                                        'Messages Available',
                                                        'Messages in Flight',
                                                        'Messages Delayed'))
        queues = self.azul_queues()
        for queue_name, queue in queues:
            print('{:<35s}{:^20s}{:^20s}{:^18s}'.format(queue_name,
                                                        queue.attributes['ApproximateNumberOfMessages'],
                                                        queue.attributes['ApproximateNumberOfMessagesNotVisible'],
                                                        queue.attributes['ApproximateNumberOfMessagesDelayed']))

    def dump(self, queue_name, path):
        sqs = boto3.resource('sqs')
        queue = sqs.get_queue_by_name(QueueName=queue_name)
        self._dump(queue, path)

    def dump_all(self):
        for queue_name, queue in self.azul_queues():
            self._dump(queue, queue_name + '.json')

    def _dump(self, queue, path):
        logger.info('Writing messages from queue "%s" to file "%s"', queue.url, path)
        messages = []
        while True:
            message_batch = queue.receive_messages(AttributeNames=['All'],
                                                   MaxNumberOfMessages=10,
                                                   VisibilityTimeout=300)
            if not message_batch:  # Nothing left in queue
                break
            else:
                messages.extend(message_batch)
        self._dump_messages(messages, queue.url, path)
        message_batches = list(more_itertools.chunked(messages, 10))
        if self._delete:
            logger.info('Removing messages from queue "%s"', queue.url)
            self._delete_messages(message_batches, queue)
        else:
            logger.info('Returning messages to queue "%s"', queue.url)
            self._return_messages(message_batches, queue)
        logger.info(f'Finished writing {path !r}')

    def _dump_messages(self, messages, queue_url, path):
        messages = [self._condense(message) for message in messages]
        with write_file_atomically(path) as file:
            content = {
                'queue': queue_url,
                'messages': messages
            }
            json.dump(content, file, indent=4)
        logger.info('Wrote %i messages', len(messages))

    def _return_messages(self, message_batches, queue):
        for message_batch in message_batches:
            batch = [dict(Id=message.message_id,
                          ReceiptHandle=message.receipt_handle,
                          VisibilityTimeout=0) for message in message_batch]
            response = queue.change_message_visibility_batch(Entries=batch)
            if len(response['Successful']) != len(batch):
                raise RuntimeError(f'Failed to return message: {response!r}')

    def _delete_messages(self, message_batches, queue):
        for message_batch in message_batches:
            response = queue.delete_messages(
                Entries=[dict(Id=message.message_id,
                              ReceiptHandle=message.receipt_handle) for message in message_batch])
            if len(response['Successful']) != len(message_batch):
                raise RuntimeError(f'Failed to delete messages: {response!r}')

    def _condense(self, message):
        """
        Prepare a message for writing to a local file.
        """
        return {
            'MessageId': message.message_id,
            'ReceiptHandle': message.receipt_handle,
            'MD5OfBody': message.md5_of_body,
            'Body': json.loads(message.body) if self._json_body else message.body,
            'Attributes': message.attributes,
        }

    def _reconstitute(self, message):
        """
        Prepare a message from a local file for submission to a queue.

        The inverse of _condense().
        """
        body = message['Body']
        if not isinstance(body, str):
            body = json.dumps(body)
        attributes = message['Attributes']
        result = {
            'Id': message['MessageId'],
            'MessageBody': body,
        }
        for key in ('MessageGroupId', 'MessageDeduplicationId'):
            try:
                result[key] = attributes[key]
            except KeyError:
                pass
        return result

    def azul_queues(self):
        sqs = boto3.resource('sqs')
        all_queues = sqs.queues.all()
        for queue in all_queues:
            _, _, queue_name = urlparse(queue.url).path.rpartition('/')
            if self._is_azul_queue(queue_name):
                yield queue_name, queue

    def _is_azul_queue(self, queue_name) -> bool:
        return any(config.unqualified_resource_name_or_none(queue_name, suffix)[1] == config.deployment_stage
                   for suffix in ('', '.fifo'))

    def feed(self, path, queue_name, force=False):
        with open(path) as file:
            content = json.load(file)
            orig_queue = content['queue']
            messages = content['messages']
        sqs = boto3.resource('sqs')
        queue = sqs.get_queue_by_name(QueueName=queue_name)
        logger.info('Writing messages from file "%s" to queue "%s"', path, queue.url)
        if orig_queue != queue.url:
            if force:
                logger.warning('Messages originating from queue "%s" are being fed into queue "%s"',
                               orig_queue, queue.url)
            else:
                raise RuntimeError(f'Cannot feed messages originating from "{orig_queue}" to "{queue.url}". '
                                   f'Use --force to override')
        message_batches = list(more_itertools.chunked(messages, 10))

        def _cleanup():
            if self._delete:
                remaining_messages = list(chain.from_iterable(message_batches))
                if len(remaining_messages) < len(messages):
                    self._dump_messages(messages, orig_queue, path)
                else:
                    assert len(remaining_messages) == len(messages)
                    logger.info('No messages were submitted, not touching local file "%s"', path)

        while message_batches:
            message_batch = message_batches[0]
            entries = [self._reconstitute(message) for message in message_batch]
            try:
                queue.send_messages(Entries=entries)
            except:
                assert message_batches
                _cleanup()
                raise
            message_batches.pop(0)

        if self._delete:
            if message_batches:
                _cleanup()
            else:
                logger.info('All messages were submitted, removing local file "%s"', path)
                os.unlink(path)

    def purge(self, queue_name):
        sqs = boto3.resource('sqs')
        queue = sqs.get_queue_by_name(QueueName=queue_name)
        self.purge_queues_safely({queue_name: queue})

    def purge_all(self):
        self.purge_queues_safely(dict(self.azul_queues()))

    def purge_queues_safely(self, queues: Mapping[str, Queue]):
        self.manage_lambdas(queues, enable=False)
        self.purge_queues_unsafely(queues)
        self.manage_lambdas(queues, enable=True)

    def purge_queues_unsafely(self, queues: Mapping[str, Queue]):
        with ThreadPoolExecutor(max_workers=len(queues)) as tpe:
            futures = [tpe.submit(self._purge_queue, queue) for queue in queues.values()]
            self._handle_futures(futures)

    def _purge_queue(self, queue: Queue):
        logger.info('Purging queue "%s"', queue.url)
        queue.purge()
        self._wait_for_queue_empty(queue)

    def _wait_for_queue_idle(self, queue: Queue):
        while True:
            num_inflight_messages = int(queue.attributes['ApproximateNumberOfMessagesNotVisible'])
            if num_inflight_messages == 0:
                break
            logger.info('Queue "%s" has %i in-flight messages', queue.url, num_inflight_messages)
            time.sleep(3)
            queue.reload()

    def _wait_for_queue_empty(self, queue: Queue):
        # Gotta have some fun some of the time
        attribute_names = tuple(map('ApproximateNumberOfMessages'.__add__, ('', 'Delayed', 'NotVisible')))
        while True:
            num_messages = sum(map(int, map(queue.attributes.get, attribute_names)))
            if num_messages == 0:
                break
            logger.info('Queue "%s" still has %i messages', queue.url, num_messages)
            time.sleep(3)
            queue.reload()

    def _manage_sqs_push(self, function_name, queue, enable: bool):
        lambda_ = boto3.client('lambda')
        response = lambda_.list_event_source_mappings(FunctionName=function_name,
                                                      EventSourceArn=queue.attributes['QueueArn'])
        mapping = one(response['EventSourceMappings'])

        def update_():
            logger.info('%s push from "%s" to lambda function "%s"',
                        'Enabling' if enable else 'Disabling', queue.url, function_name)
            lambda_.update_event_source_mapping(UUID=mapping['UUID'],
                                                Enabled=enable)

        while True:
            state = mapping['State']
            logger.info('Push from "%s" to lambda function "%s" is in state "%s".',
                        queue.url, function_name, state)
            if state in ('Disabling', 'Enabling'):
                pass
            elif state == 'Enabled':
                if enable:
                    break
                else:
                    update_()
            elif state == 'Disabled':
                if enable:
                    update_()
                else:
                    break
            else:
                raise NotImplementedError(state)
            time.sleep(3)
            mapping = lambda_.get_event_source_mapping(UUID=mapping['UUID'])

    def manage_lambdas(self, queues: Mapping[str, Queue], enable: bool):
        """
        Enable or disable the readers and writers of the given queues
        """
        with ThreadPoolExecutor(max_workers=len(queues)) as tpe:
            futures = []
            for queue_name, queue in queues.items():
                if queue_name == config.notify_queue_name:
                    futures.append(tpe.submit(self._manage_lambda, config.indexer_name, enable))
                    futures.append(tpe.submit(self._manage_sqs_push, config.indexer_name + '-index', queue, enable))
                elif queue_name == config.token_queue_name:
                    futures.append(tpe.submit(self._manage_sqs_push, config.indexer_name + '-write', queue, enable))
            self._handle_futures(futures)
            futures = [tpe.submit(self._wait_for_queue_idle, queue) for queue in queues.values()]
            self._handle_futures(futures)

    def _manage_lambda(self, function_name, enable: bool):
        self._lambdas.manage_lambda(function_name, enable)

    @memoized_property
    def _lambdas(self):
        return Lambdas()

    def _handle_futures(self, futures):
        errors = []
        for future in as_completed(futures):
            e = future.exception()
            if e:
                errors.append(e)
                logger.error('Exception in worker thread', exc_info=e)
        if errors:
            raise RuntimeError(errors)
