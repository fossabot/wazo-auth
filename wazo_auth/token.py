# Copyright 2015-2019 The Wazo Authors  (see the AUTHORS file)
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import os
import re
import time
from threading import Timer

from datetime import datetime

from xivo_bus.resources.auth.events import SessionDeletedEvent

logger = logging.getLogger(__name__)

DEFAULT_XIVO_UUID = os.getenv('XIVO_UUID')


class Token:
    def __init__(
        self,
        id_,
        auth_id,
        xivo_user_uuid,
        xivo_uuid,
        issued_t,
        expire_t,
        acls,
        metadata,
        session_uuid,
    ):
        self.token = id_
        self.auth_id = auth_id
        self.xivo_user_uuid = xivo_user_uuid
        self.xivo_uuid = xivo_uuid
        self.issued_t = issued_t
        self.expire_t = expire_t
        self.acls = acls
        self.metadata = metadata
        self.session_uuid = session_uuid

    def __eq__(self, other):
        return (
            self.token == other.token
            and self.auth_id == other.auth_id
            and self.xivo_user_uuid == other.xivo_user_uuid
            and self.xivo_uuid == other.xivo_uuid
            and self.issued_t == other.issued_t
            and self.expire_t == other.expire_t
            and self.acls == other.acls
            and self.metadata == other.metadata
            and self.session_uuid == other.session_uuid
        )

    def __ne__(self, other):
        return not self == other

    @staticmethod
    def _format_local_time(t):
        if not t:
            return None
        return datetime.fromtimestamp(t).isoformat()

    @staticmethod
    def _format_utc_time(t):
        if not t:
            return None
        return datetime.utcfromtimestamp(t).isoformat()

    def to_dict(self):
        return {
            'token': self.token,
            'auth_id': self.auth_id,
            'xivo_user_uuid': self.xivo_user_uuid,
            'xivo_uuid': self.xivo_uuid,
            'issued_at': self._format_local_time(self.issued_t),
            'expires_at': self._format_local_time(self.expire_t),
            'utc_issued_at': self._format_utc_time(self.issued_t),
            'utc_expires_at': self._format_utc_time(self.expire_t),
            'acls': self.acls,
            'metadata': self.metadata,
            'session_uuid': self.session_uuid,
        }

    def is_expired(self):
        return self.expire_t and time.time() > self.expire_t

    def matches_required_acl(self, required_acl):
        if required_acl is None:
            return True

        for user_acl in self.acls:
            user_acl_regex = self._transform_acl_to_regex(user_acl)
            if re.match(user_acl_regex, required_acl):
                return True
        return False

    def _transform_acl_to_regex(self, acl):
        acl_regex = re.escape(acl).replace('\\*', '[^.]*?').replace('\\#', '.*?')
        acl_regex = self._transform_acl_me_to_uuid_or_me(acl_regex)
        return re.compile('^{}$'.format(acl_regex))

    def _transform_acl_me_to_uuid_or_me(self, acl_regex):
        acl_regex = acl_regex.replace(
            '\\.me\\.', '\\.(me|{auth_id})\\.'.format(auth_id=self.auth_id)
        )
        if acl_regex.endswith('\\.me'):
            acl_regex = '{acl_start}\\.(me|{auth_id})'.format(
                acl_start=acl_regex[:-4], auth_id=self.auth_id
            )
        return acl_regex


class ExpiredTokenRemover:
    def __init__(self, config, dao, bus_publisher):
        self._dao = dao
        self._bus_publisher = bus_publisher
        self._cleanup_interval = config['token_cleanup_interval']
        self._debug = config['debug']

    def run(self):
        self._cleanup()
        self._reschedule(self._cleanup_interval)

    def _cleanup(self):
        try:
            tokens, sessions = self._dao.token.delete_expired_tokens_and_sessions()
        except Exception:
            logger.warning(
                'failed to remove expired tokens and sessions', exc_info=self._debug
            )
            return

        for session in sessions:
            event_args = {
                'uuid': session['uuid'],
                'user_uuid': None,
                'tenant_uuid': None,
            }
            for token in tokens:
                if token['session_uuid'] == session['uuid']:
                    event_args['user_uuid'] = token['auth_id']
                    event_args['tenant_uuid'] = token['metadata'].get('tenant_uuid')
                    break
            else:
                logger.warning(
                    'session deleted without token associated: %s' % session['uuid']
                )

            event = SessionDeletedEvent(**event_args)
            self._bus_publisher.publish(event)

    def _reschedule(self, interval):
        thread = Timer(interval, self.run)
        thread.daemon = True
        thread.start()
