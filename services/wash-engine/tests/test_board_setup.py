import unittest
from unittest.mock import patch,Mock
from uuid import uuid4
from fastapi import HTTPException
from pydantic import ValidationError
from app.board_setup import BoardChoice,request_board,host_board


class BoardSetupTests(unittest.TestCase):
    def test_payload_rejects_commands_and_extra_fields(self):
        for data in ({'board_id':'../../bad'},{'board_id':'cl3566-a-e','path':'/tmp/x'}):
            with self.assertRaises(ValidationError):BoardChoice(request_id=uuid4(),**data)

    def test_closed_and_busy_installation_never_calls_host(self):
        payload=BoardChoice(board_id='cl3566-a-e',request_id=uuid4())
        with patch('app.board_setup.httpx.Client') as client:
            with self.assertRaises(HTTPException):request_board(payload,{'complete':True})
            with patch('app.board_setup.require_idle',side_effect=HTTPException(409,'busy')):
                with self.assertRaises(HTTPException):request_board(payload,{'complete':False})
            client.assert_not_called()

    def test_only_fixed_host_action_and_receipt_fields_are_used(self):
        payload=BoardChoice(board_id='cl3566-a-e',request_id=uuid4())
        response=Mock(status_code=202);response.json.return_value={'ok':True,'request_id':str(payload.request_id),'action':'board-cl3566-a-e','status':'accepted','secret':'hidden'}
        with patch('app.board_setup.require_idle'),patch('app.board_setup.httpx.Client') as client:
            client.return_value.__enter__.return_value.post.return_value=response
            result=request_board(payload,{'complete':False})
            body=client.return_value.__enter__.return_value.post.call_args.kwargs['json']
            self.assertEqual(body,{'action':'board-cl3566-a-e','request_id':str(payload.request_id),'actor':'installer'})
            self.assertNotIn('secret',result)
