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

from xivo_auth.helpers import now, later, values_to_dict


class Token(object):

    def __init__(self, token, uuid, now_, later_):
        self.token = token
        self.uuid = uuid
        self.issued_at = now_
        self.expires_at = later_

    def to_dict(self):
        return self.__dict__

    def is_expired(self):
        return now() > self.expires_at

    @classmethod
    def from_dict(cls, d):
        return Token(d['token'], d['uuid'], d['issued_at'], d['expires_at'])


class Manager(object):

    consul_token_kv = 'xivo/xivo-auth/tokens/{}'

    def __init__(self, config, consul, celery, acl_generator=None):
        self._acl_generator = acl_generator or _ACLGenerator()
        self._default_expiration = config['default_token_lifetime']
        self._consul = consul
        self._celery = celery

    def new_token(self, uuid, expiration=None):
        from xivo_auth import events
        rules = self._acl_generator.create(uuid)
        consul_token = self._consul.acl.create(rules=rules)
        expiration = expiration or self._default_expiration
        token = Token(consul_token, uuid, now(), later(expiration))
        task_id = self._get_token_hash(token)
        self._push_token_data(token)
        events.clean_token.apply_async(args=[consul_token], countdown=expiration, task_id=task_id)
        return token

    def remove_token(self, token):
        task_id = self._get_token_hash(token)
        self._celery.control.revoke(task_id)
        self.remove_expired_token(token)

    def remove_expired_token(self, token):
        self._consul.acl.destroy(token)
        self._consul.kv.delete('xivo/xivo-auth/tokens/{}'.format(token), recurse=True)

    def get(self, consul_token):
        key = self.consul_token_kv.format(consul_token)
        index, values = self._consul.kv.get(key, recurse=True)
        if not values:
            raise LookupError('No such token {}'.format(consul_token))

        return Token.from_dict(values_to_dict(values)['xivo']['xivo-auth']['tokens'][consul_token])

    def _push_token_data(self, token):
        consul_token = token.token
        key_tpl = 'xivo/xivo-auth/tokens/{token}/{key}'
        for key, value in token.to_dict().iteritems():
            complete_key = key_tpl.format(token=consul_token, key=key)
            self._consul.kv.put(complete_key, value)

    def _get_token_hash(self, token):
        return hashlib.sha256('{token}'.format(token=token)).hexdigest()


class _ACLGenerator(object):

    def create(self, uuid):
        rules = {'key': {'': {'policy': 'deny'},
                         'xivo/private/{uuid}'.format(uuid=uuid): {'policy': 'write'}}}
        return json.dumps(rules)