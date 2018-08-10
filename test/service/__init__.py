import os
import sys
import time
import logging
import requests
from shared import AzulTestCase
from threading import Thread
from service.data_generator.fake_data_utils import ElasticsearchFakeDataLoader
from chalice.local import LocalDevServer
from chalice.config import Config as ChaliceConfig
from azul import Config as AzulConfig

log = logging.getLogger(__name__)


class ChaliceServerThread(Thread):
    def __init__(self, app, config, host, port):
        super().__init__()
        self.server_wrapper = LocalDevServer(app, config, host, port)

    def run(self):
        self.server_wrapper.serve_forever()

    def kill_thread(self):
        self.server_wrapper.server.shutdown()
        self.server_wrapper.server.server_close()

    def address(self):
        return self.server_wrapper.server.server_address


class WebServiceTestCase(AzulTestCase):
    data_loader = None

    @property
    def base_url(self):
        address = self.server_thread.address()
        return f"http://{address[0]}:{address[1]}/"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.data_loader = ElasticsearchFakeDataLoader()
        cls.data_loader.load_data()
        cls.path_to_app = os.path.join(AzulConfig().project_root, 'lambdas', 'service')
        sys.path.append(cls.path_to_app)
        from app import app
        cls.app = app

    @classmethod
    def tearDownClass(cls):
        cls.data_loader.clean_up()
        sys.path.remove(cls.path_to_app)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        log.debug("Setting up tests")
        log.debug("Created Thread")
        self.server_thread = ChaliceServerThread(self.app, ChaliceConfig(), 'localhost', 0)
        log.debug("Started Thread")
        self.server_thread.start()
        deadline = time.time() + 10
        while True:
            url = self.base_url
            try:
                response = requests.get(url)
                response.raise_for_status()
            except Exception:
                if time.time() > deadline:
                    raise
                log.debug("Unable to connect to server", exc_info=True)
                time.sleep(1)
            else:
                break

    def tearDown(self):
        log.debug("Tearing Down Data")
        self.server_thread.kill_thread()
        self.server_thread.join(timeout=10)
        if self.server_thread.is_alive():
            self.fail('Thread is still alive after joining')