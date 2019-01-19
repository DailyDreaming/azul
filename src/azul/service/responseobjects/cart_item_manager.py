import base64
import hashlib
import json
import uuid

from azul import config
from azul.service.responseobjects.dynamo_data_access import DynamoDataAccessor
from azul.service.responseobjects.elastic_request_builder import ElasticTransformDump as EsTd
from azul.service.responseobjects.step_function_helper import StepFunctionHelper


class CartItemManager:
    """
    Helper functions to handle read/write/update of carts and cart items
    """
    step_function_helper = StepFunctionHelper()

    def __init__(self):
        self.dynamo_accessor = DynamoDataAccessor()

    def encode_params(self, params):
        return base64.urlsafe_b64encode(bytes(json.dumps(params), encoding='utf-8')).decode('utf-8')

    def decode_token(self, token):
        return json.loads(base64.urlsafe_b64decode(token).decode('utf-8'))

    def check_cart_permission(self, user_id, cart_id):
        """
        Check if the user has a cart with the given id.  Raise exception if user does not have access to the cart
        """
        if self.get_cart(user_id, cart_id) is None:
            raise ResourceAccessError('Cart does not exist')

    def create_cart(self, user_id, cart_name, default):
        """
        Add a cart to the cart table and return the ID of the created cart
        An error will be raised if the user already has a cart of the same name or
        if a default cart is being created while one already exists
        """
        query_dict = {'UserId': user_id, 'CartName': cart_name}
        if self.dynamo_accessor.count(table_name=config.dynamo_cart_table_name,
                                      key_conditions=query_dict,
                                      index_name='UserCartNameIndex') > 0:
            raise DuplicateItemError(f'Cart `{cart_name}` already exists')

        if default:
            if self.dynamo_accessor.count(table_name=config.dynamo_cart_table_name,
                                          key_conditions={'UserId': user_id},
                                          filters={'DefaultCart': True},
                                          index_name='UserIndex') > 0:
                raise DuplicateItemError('Default cart already exists')

        cart_id = 'default' if default else str(uuid.uuid4())
        self.dynamo_accessor.insert_item(config.dynamo_cart_table_name,
                                         item={'CartId': cart_id, 'DefaultCart': default, **query_dict})
        return cart_id

    def get_cart(self, user_id, cart_id):
        return self.dynamo_accessor.get_item(config.dynamo_cart_table_name,
                                             keys={'UserId': user_id, 'CartId': cart_id})

    def get_user_carts(self, user_id):
        return list(self.dynamo_accessor.query(table_name=config.dynamo_cart_table_name,
                                               key_conditions={'UserId': user_id},
                                               index_name='UserIndex'))

    def delete_cart(self, user_id, cart_id):
        self.dynamo_accessor.delete_by_key(config.dynamo_cart_item_table_name,
                                           {'CartId': cart_id})
        return self.dynamo_accessor.delete_item(config.dynamo_cart_table_name,
                                                {'UserId': user_id, 'CartId': cart_id})

    def update_cart(self, user_id, cart_id, update_attributes, validate_attributes=True):
        """
        Update the attributes of a cart and return the updated item
        Only accepted attributes will be updated and any others will be ignored
        """
        self.check_cart_permission(user_id, cart_id)
        if validate_attributes:
            accepted_attributes = {'CartName', 'Description'}
            for key in list(update_attributes.keys()):
                if key not in accepted_attributes:
                    del update_attributes[key]

        if 'CartName' in update_attributes.keys():
            matching_carts = list(self.dynamo_accessor.query(table_name=config.dynamo_cart_table_name,
                                                             key_conditions={
                                                                 'UserId': user_id,
                                                                 'CartName': update_attributes['CartName']
                                                             },
                                                             index_name='UserCartNameIndex'))
            # There cannot be more than one matching cart because of the index's keys
            if len(matching_carts) > 0 and matching_carts[0]['CartId'] != cart_id:
                raise DuplicateItemError(f'Cart `{update_attributes["CartName"]}` already exists')

        return self.dynamo_accessor.update_item(config.dynamo_cart_table_name,
                                                {'UserId': user_id, 'CartId': cart_id},
                                                update_values=update_attributes)

    def create_cart_item_id(self, cart_id, entity_id, entity_type, bundle_uuid, bundle_version):
        return hashlib.sha256(f'{cart_id}/{entity_id}/{bundle_uuid}/{bundle_version}/{entity_type}'.encode('utf-8')).hexdigest()

    def add_cart_item(self, user_id, cart_id, entity_id, bundle_uuid, bundle_version, entity_type):
        """
        Add an item to a cart and return the created item ID
        An error will be raised if the cart does not exist or does not belong to the user
        """
        # TODO: Cart item should have some user readable name
        self.check_cart_permission(user_id, cart_id)
        item_id = self.create_cart_item_id(cart_id, entity_id, entity_type, bundle_uuid, bundle_version)
        self.dynamo_accessor.insert_item(
            config.dynamo_cart_item_table_name,
            {
                'CartItemId': item_id, 'CartId': cart_id, 'EntityId': entity_id,
                'BundleUuid': bundle_uuid, 'BundleVersion': bundle_version, 'EntityType': entity_type
            })
        return item_id

    def get_cart_items(self, user_id, cart_id):
        """
        Get all items in a cart
        An error will be raised if the cart does not exist or does not belong to the user
        """
        self.check_cart_permission(user_id, cart_id)
        return list(self.dynamo_accessor.query(table_name=config.dynamo_cart_item_table_name,
                                               key_conditions={'CartId': cart_id}))

    def delete_cart_item(self, user_id, cart_id, item_id):
        """
        Delete an item from a cart and return the deleted item if it exists, None otherwise
        An error will be raised if the cart does not exist or does not belong to the user
        """
        if self.get_cart(user_id, cart_id) is None:
            raise ResourceAccessError('Cart does not exist')
        return self.dynamo_accessor.delete_item(config.dynamo_cart_item_table_name,
                                                keys={'CartId': cart_id, 'CartItemId': item_id})

    def transform_hit_to_cart_item(self, hit, entity_type, cart_id):
        """
        Transform a hit from ES to the schema for the cart item table
        """
        if entity_type == 'files':
            entity_id_field = 'uuid'
        elif entity_type == 'specimens':
            entity_id_field = 'biomaterial_id'
        elif entity_type == 'projects':
            entity_id_field = 'project_shortname'
        else:
            raise ValueError('entity_type must be one of files, specimens, or projects')

        bundle = hit['bundles'][0]  # TODO: handle entities with multiple bundles
        entity = hit['contents'][entity_type][0]
        cart_item = {
            'CartId': cart_id,
            'EntityId': entity[entity_id_field],
            'EntityType': entity_type,
            'BundleUuid': bundle['uuid'],
            'BundleVersion': bundle['version'],
        }
        item_id = self.create_cart_item_id(cart_item['CartId'], cart_item['EntityId'], cart_item['EntityType'],
                                           cart_item['BundleUuid'], cart_item['BundleVersion'])
        cart_item['CartItemId'] = item_id
        return cart_item

    def start_batch_cart_item_write(self, user_id, cart_id, write_params):
        """
        Trigger the job that will write the cart items and return a token to be used to check the job status

        Write params should have the format:
        {
            'filters': str,
            'entity_type': str,
            'cart_id': str,
            'item_count': int,
            'batch_size': int
        }
        """
        self.check_cart_permission(user_id, cart_id)
        execution_id = str(uuid.uuid4())
        self.step_function_helper.start_execution(config.cart_item_state_machine_name,
                                                  execution_name=execution_id,
                                                  execution_input=write_params)
        return self.encode_params({'execution_id': execution_id})

    def get_batch_cart_item_write_status(self, token):
        params = self.decode_token(token)
        execution_id = params['execution_id']
        return self.step_function_helper.describe_execution(config.cart_item_state_machine_name, execution_id)['status']

    def write_cart_item_batch(self, entity_type, filters, cart_id, batch_size, search_after):
        """
        Query ES for one page of items matching the entity type and filters and return
        the number of items written and the search_after for the next page
        """
        hits, next_search_after = EsTd().transform_cart_item_request(
            entity_type=entity_type,
            filters=filters,
            search_after=search_after,
            size=batch_size
        )
        self.dynamo_accessor.batch_write(config.dynamo_cart_item_table_name,
                                         [self.transform_hit_to_cart_item(hit, entity_type, cart_id) for hit in hits])
        return len(hits), next_search_after


class ResourceAccessError(Exception):
    def __init__(self, msg):
        self.msg = msg


class DuplicateItemError(Exception):
    def __init__(self, msg):
        self.msg = msg