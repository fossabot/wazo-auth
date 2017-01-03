# -*- coding: utf-8 -*-
#
# Copyright 2016 The Wazo Authors  (see the AUTHORS file)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>

import unittest

from hamcrest import assert_that, calling, equal_to, raises
from mock import sentinel as s

from ..database import Storage
from ..token import Token, TokenPayload, UnknownTokenException


class TestStorage(unittest.TestCase):

    def setUp(self):
        self.crud = MockedCrud()

    def test_get_token(self):
        storage = Storage(self.crud)

        result = storage.get_token(s.token_id)

        expected_token = Token(s.token_id, s.auth_id, s.xivo_user_uuid,
                               s.xivo_uuid, s.issued_t, s.expire_t, s.acls)
        assert_that(result, equal_to(expected_token))

    def test_get_token_not_found(self):
        storage = Storage(self.crud)

        assert_that(
            calling(storage.get_token).with_args(s.inexistant_token),
            raises(UnknownTokenException))

    def test_create_token(self):
        token_data = {
            'auth_id': s.auth_id,
            'xivo_user_uuid': s.xivo_user_uuid,
            'xivo_uuid': s.xivo_uuid,
            'issued_t': s.issued_t,
            'expire_t': s.expire_t,
            'acls': s.acls
        }
        storage = Storage(self.crud)

        payload = TokenPayload(**token_data)
        result = storage.create_token(payload)

        expected_token = Token(s.token_uuid, **token_data)
        assert_that(result, equal_to(expected_token))
        self.crud.assert_created_with(token_data)

    def test_remove_token(self):
        storage = Storage(self.crud)

        storage.remove_token(s.token_uuid)

        self.crud.assert_deleted(s.token_uuid)


class MockedCrud(object):

    def __init__(self):
        self._create_args = None
        self._deleted_token = None

    def assert_created_with(self, args):
        assert_that(args, equal_to(self._create_args))

    def assert_deleted(self, token_uuid):
        assert_that(token_uuid, equal_to(self._deleted_token))

    def create(self, token_payload):
        self._create_args = token_payload
        return s.token_uuid

    def delete(self, token_uuid):
        self._deleted_token = token_uuid

    def get(self, token_id):
        if token_id == s.inexistant_token:
            return None

        return {
            'uuid': token_id,
            'auth_id': s.auth_id,
            'xivo_user_uuid': s.xivo_user_uuid,
            'xivo_uuid': s.xivo_uuid,
            'issued_t': s.issued_t,
            'expire_t': s.expire_t,
            'acls': s.acls,
        }