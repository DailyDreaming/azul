import json
import logging

from typing import Optional

from azul.service.responseobjects.elastic_request_builder import BadArgumentException

logger = logging.getLogger(__name__)


class AbstractService:

    # FIXME: Convert back to instance method once #566 is solved
    #  https://github.com/DataBiosphere/azul/issues/566
    @classmethod
    def parse_filters(cls, filters: Optional[str]):
        """
        Parses filters. Handles default cases where filters are None (not set) or {}
        :param filters: string of python interpretable data
        :raises ValueError: Will raise a ValueError if token is misformatted or invalid
        :return: python literal
        """
        default_filters = {}
        if filters is None:
            return default_filters
        try:
            filters = json.loads(filters or '{}')
        except ValueError as e:
            logger.error('Malformed filters parameter: {}'.format(e))
            raise BadArgumentException('Malformed filters parameter')
        else:
            return default_filters if filters == {} else filters
