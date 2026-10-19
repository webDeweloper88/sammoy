from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import Mock,patch
import httpx
from app import http_pool

class HttpPoolTests(unittest.TestCase):
    def setUp(self):http_pool.close_all()
    def tearDown(self):http_pool.close_all()
    def test_reuses_transport_but_not_responses(self):
        client=Mock(is_closed=False)
        with patch.object(http_pool.httpx,'Client',return_value=client) as factory:
            for _ in range(3):
                with http_pool.sync_client(scope='wallet',timeout=4) as c:c.post('http://peer/action')
            factory.assert_called_once();self.assertEqual(client.post.call_count,3)
            client.close.assert_not_called()
            http_pool.close_all();client.close.assert_called_once()
    def test_io_and_wallet_have_independent_capacity(self):
        with patch.object(http_pool.httpx,'Client',side_effect=lambda **kw:Mock(is_closed=False)) as factory:
            with http_pool.sync_client(scope='wallet',timeout=4) as wallet:
                with http_pool.sync_client(scope='io',timeout=2) as io:self.assertIsNot(wallet,io)
            self.assertEqual(factory.call_count,2)
    def test_concurrent_first_use_creates_one_client(self):
        with patch.object(http_pool.httpx,'Client',return_value=Mock(is_closed=False)) as factory:
            def get(_):
                with http_pool.sync_client(scope='wallet',timeout=4) as c:return id(c)
            with ThreadPoolExecutor(max_workers=8) as pool:ids=list(pool.map(get,range(20)))
            self.assertEqual(len(set(ids)),1);factory.assert_called_once()
    def test_failed_command_is_not_retried(self):
        client=Mock(is_closed=False);client.post.side_effect=httpx.ReadError('connection lost')
        with patch.object(http_pool.httpx,'Client',return_value=client):
            with self.assertRaises(httpx.ReadError):
                with http_pool.sync_client(scope='wallet',timeout=4) as c:c.post('http://peer/action')
            client.post.assert_called_once()
