# -*- coding: utf-8 -*-
#
# Copyright (C) 2015 Avencall
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

import hashlib
import json
import logging
import socket

from unidecode import unidecode
from uuid import UUID
from requests.exceptions import ConnectionError

from xivo_auth.helpers import now, later, values_to_dict, FlatDict

logger = logging.getLogger(__name__)


class ManagerException(Exception):
    pass


class UnknownTokenException(ManagerException):

    code = 404

    def __str__(self):
        return 'No such token'


class MissingACLTokenException(ManagerException):

    code = 403

    def __init__(self, required_acl):
        super(MissingACLTokenException, self).__init__()
        self._required_acl = required_acl

    def __str__(self):
        return 'Unauthorized for {}'.format(unidecode(self._required_acl))


class _ConsulConnectionException(ManagerException):

    code = 500

    def __str__(self):
        return 'Connection to consul failed'


class _RabbitMQConnectionException(ManagerException):

    code = 500

    def __str__(self):
        return 'Connection to rabbitmq failed'


class Token(object):

    def __init__(self, token, auth_id, xivo_user_uuid, now_, later_, acls, name=None):
        self.token = token
        self.auth_id = auth_id
        self.xivo_user_uuid = xivo_user_uuid
        self.issued_at = now_
        self.expires_at = later_
        self.acls = acls
        self.name = name

    def to_consul(self):
        acls = {acl: acl for acl in self.acls}
        return {'token': self.token,
                'auth_id': self.auth_id,
                'xivo_user_uuid': self.xivo_user_uuid,
                'issued_at': self.issued_at,
                'expires_at': self.expires_at,
                'acls': acls or None,
                'name': self.name}

    def to_dict(self):
        return {'token': self.token,
                'auth_id': self.auth_id,
                'xivo_user_uuid': self.xivo_user_uuid,
                'issued_at': self.issued_at,
                'expires_at': self.expires_at,
                'acls': self.acls}

    def is_expired(self):
        return self.expires_at and now() > self.expires_at

    def matches_required_acl(self, required_acl):
        # TODO: add pattern matching
        return required_acl is None or required_acl in self.acls

    @classmethod
    def from_consul(cls, d):
        acls = d.get('acls', {}) or {}
        name = d.get('name', '')

        return Token(d['token'], d['auth_id'], d['xivo_user_uuid'],
                     d['issued_at'], d['expires_at'], acls.keys(), name)


class Manager(object):

    def __init__(self, config, storage, celery, consul_acl_generator=None):
        self._consul_acl_generator = consul_acl_generator or _ConsulACLGenerator()
        self._default_expiration = config['default_token_lifetime']
        self._storage = storage
        self._celery = celery

    def new_token(self, backend, login, args):
        from xivo_auth import tasks

        auth_id, xivo_user_uuid = backend.get_ids(login, args)
        rules = self._consul_acl_generator.create_from_backend(backend, login, args)
        acls = backend.get_acls(login, args)
        expiration = args.get('expiration', self._default_expiration)
        token = Token(None, auth_id, xivo_user_uuid, now(), later(expiration), acls)

        self._storage.put_token(token, rules)

        task_id = self._get_token_hash(token)
        try:
            tasks.clean_token.apply_async(args=[token.token], countdown=expiration, task_id=task_id)
        except socket.error:
            raise _RabbitMQConnectionException()
        return token

    def remove_token(self, token):
        task_id = self._get_token_hash(token)
        try:
            self._celery.control.revoke(task_id)
        except socket.error:
            raise _RabbitMQConnectionException()
        self._storage.remove_token(token)

    def remove_expired_token(self, token):
        self._storage.remove_token(token)

    def get(self, consul_token, required_acl):
        token = self._storage.get_token(consul_token)

        if token.is_expired():
            raise UnknownTokenException()

        if not token.matches_required_acl(required_acl):
            raise MissingACLTokenException(required_acl)

        return token

    def _get_token_hash(self, token):
        return hashlib.sha256('{token}'.format(token=token)).hexdigest()


class _ConsulACLGenerator(object):

    def create_from_backend(self, backend, login, args):
        backend_specific_acls = backend.get_consul_acls(login, args)
        return self.create(backend_specific_acls)

    def create(self, acls):
        rules = {'key': {'': {'policy': 'deny'}}}
        for rule_policy in acls:
            rules['key'][rule_policy['rule']] = {'policy': rule_policy['policy']}

        return json.dumps(rules)


class Storage(object):

    _TOKEN_KEY_FORMAT = 'xivo/xivo-auth/tokens/{}'
    _TOKEN_NAME_KEY_FORMAT = 'xivo/xivo-auth/tokens/{}/name'
    _NAME_INDEX_KEY_FORMAT = 'xivo/xivo-auth/token-names/{}'

    def __init__(self, consul):
        self._consul = consul

    def get_token(self, token_id):
        self._check_valid_token_id(token_id)

        key = self._TOKEN_KEY_FORMAT.format(token_id)
        try:
            _, values = self._consul.kv.get(key, recurse=True)
        except ConnectionError as e:
            logger.error('Connection to consul failed: %s', e)
            raise _ConsulConnectionException()

        if not values:
            raise UnknownTokenException()

        return Token.from_consul(values_to_dict(values)['xivo']['xivo-auth']['tokens'][token_id])

    def put_token(self, token, rules):
        try:
            if token.name:
                indexed_token_id = self._get_token_id_by_name(token.name)
                if indexed_token_id:
                    if token.token and indexed_token_id != token.token:
                        logger.warning('Ignoring provided token ID for token named "%s"', token.name)
                    token.token = indexed_token_id
            elif token.token:
                token.name = self._get_token_name(token.token)

            if token.token:
                self._consul.acl.update(token.token, rules=rules)
            else:
                token.token = self._consul.acl.create(rules=rules)

            if token.name:
                key = self._NAME_INDEX_KEY_FORMAT.format(token.name)
                self._consul.kv.put(key, token.token)

            self._push_token_data(token)
        except ConnectionError as e:
            logger.error('Connection to consul failed: %s', e)
            raise _ConsulConnectionException()

    def remove_token(self, token_id):
        self._check_valid_token_id(token_id)

        try:
            token_name = self._get_token_name(token_id)
            self._consul.acl.destroy(token_id)
            self._consul.kv.delete(self._TOKEN_KEY_FORMAT.format(token_id), recurse=True)
            if token_name:
                self._consul.kv.delete(self._NAME_INDEX_KEY_FORMAT.format(token_name))
        except ConnectionError as e:
            logger.error('Connection to consul failed: %s', e)
            raise _ConsulConnectionException()

    def _get_token_name(self, token_id):
        _, value = self._consul.kv.get(self._TOKEN_NAME_KEY_FORMAT.format(token_id))
        if not value:
            return None
        return value['Value']

    def _get_token_id_by_name(self, token_name):
        key = self._NAME_INDEX_KEY_FORMAT.format(token_name)
        _, value = self._consul.kv.get(key)
        if not value:
            return None
        return value['Value']

    def _push_token_data(self, token):
        flat_dict = FlatDict({'xivo': {'xivo-auth': {'tokens': {token.token: token.to_consul()}}}})
        for key, value in flat_dict.iteritems():
            self._consul.kv.put(key, value)

    def _check_valid_token_id(self, token_id):
        try:
            UUID(hex=token_id)
        except ValueError as e:
            logger.warning('Invalid token ID: %s', e)
            raise UnknownTokenException()
