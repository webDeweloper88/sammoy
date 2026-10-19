import unittest
from unittest.mock import patch
from app.wallet_operation import card_operation, status_proof
from app import wallet_client, wallet_api
from app.wallet_replication import WalletUnavailable


class WalletOperationTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {'enabled': True, 'site_id': 'SITE', 'local_post': 1,
                    'primary_post': 1, 'standby_post': 2, 'generation': 3,
                    'single_node': False, 'peer_urls': {'1':'http://10.0.0.1','2':'http://10.0.0.2'}}

    def test_proofs_reused_only_inside_one_operation_and_return_detached_values(self):
        with patch.object(wallet_api, 'rpc', return_value={'generation':3}) as rpc:
            with card_operation():
                result = status_proof(self.cfg, 1)
                result['generation'] = 99
                with card_operation():
                    self.assertEqual(status_proof(self.cfg, 1)['generation'], 3)
                self.assertEqual(rpc.call_count, 1)
            with card_operation(): status_proof(self.cfg, 1)
            status_proof(self.cfg, 1)
            self.assertEqual(rpc.call_count, 3)

    def test_expiry_generation_and_peer_address_require_new_proof(self):
        with patch.object(wallet_api, 'rpc', return_value={}) as rpc, patch('app.wallet_operation.time.monotonic', return_value=10) as clock:
            with card_operation():
                status_proof(self.cfg, 1)
                clock.return_value=12.1
                status_proof(self.cfg, 1)
                self.cfg['generation']=4
                status_proof(self.cfg, 1)
                self.cfg['peer_urls']['1']='http://10.0.0.3'
                status_proof(self.cfg, 1)
            self.assertEqual(rpc.call_count, 4)

    def test_failed_proof_is_not_cached_and_scope_clears_on_exception(self):
        with patch.object(wallet_api, 'rpc', side_effect=[WalletUnavailable('offline'), {}, {}]) as rpc:
            with self.assertRaises(RuntimeError):
                with card_operation():
                    with self.assertRaises(WalletUnavailable): status_proof(self.cfg, 1)
                    status_proof(self.cfg, 1)
                    raise RuntimeError('failed transfer')
            status_proof(self.cfg, 1)
            self.assertEqual(rpc.call_count, 3)

    def test_commands_and_card_reads_are_never_cached_and_are_authority_fenced(self):
        def response(cfg, post, action, payload):
            if action=='status':
                return {'local_post':post,'primary_post':1,'generation':3,
                        'device_wallet_protocol':2,'bonus_protocol':1}
            return {'card': {'state': {}}, 'result': {}}
        with patch.object(wallet_api, 'configuration', return_value=self.cfg), patch.object(wallet_api, 'rpc', side_effect=response) as rpc:
            with card_operation():
                for step in ('checkpoint','prepare_return','complete_return'):
                    wallet_client.execute('stable:'+step,'CARD',{'action':step,'post_no':1,'wallet_protocol':2,'remaining_bonus_sum':100})
                wallet_client.inspect('CARD')
                wallet_client.inspect('CARD')
            calls=rpc.call_args_list
            self.assertEqual(sum(c.args[2]=='status' for c in calls),2)
            writes=[c for c in calls if c.args[2]=='execute']
            self.assertEqual(len(writes),3)
            self.assertEqual(sum(c.args[2]=='inspect' for c in calls),2)
            for c in writes:self.assertEqual(c.args[3]['expected_authority'],{'primary_post':1,'generation':3})
