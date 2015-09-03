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

import xivo_dao

from xivo_auth import BaseAuthenticationBackend

from xivo_dao import user_dao


class XiVOUser(BaseAuthenticationBackend):

    def __init__(self, config):
        xivo_dao.init_db_from_config(config)

    def get_acls(self, username, args):
        identifier, _ = self.get_ids(username, args)
        rules = [{'rule': 'xivo/private/{identifier}'.format(identifier=identifier),
                  'policy': 'write'}]
        return rules

    def get_ids(self, username, args):
        user_uuid = user_dao.get_uuid_by_username(username)
        return user_uuid, user_uuid

    def verify_password(self, login, password):
        return user_dao.check_username_password(login, password)
