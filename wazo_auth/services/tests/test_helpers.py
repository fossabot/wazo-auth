# Copyright 2018-2019 The Wazo Authors  (see the AUTHORS file)
# SPDX-License-Identifier: GPL-3.0-or-later

from hamcrest import assert_that, contains_inanyorder
from uuid import uuid4
from unittest import TestCase
from mock import Mock

from wazo_auth.services.helpers import TenantTree

# This test will use the following tenant scructure
#         top
#       /  |  \
#      a   e   h
#     / \  |
#    d  b  f
#       /\
#      g  c


def tenant(name, parent, uuid=None):
    uuid = uuid or uuid4()
    return {'uuid': uuid, 'name': name, 'parent_uuid': parent}


class TestTenantTree(TestCase):
    def setUp(self):
        top_tenant_uuid = uuid4()

        self.top = tenant('top', top_tenant_uuid, top_tenant_uuid)
        self.a = tenant('a', self.top['uuid'])
        self.b = tenant('b', self.a['uuid'])
        self.c = tenant('c', self.b['uuid'])
        self.d = tenant('d', self.a['uuid'])
        self.e = tenant('e', self.top['uuid'])
        self.f = tenant('f', self.e['uuid'])
        self.g = tenant('g', self.b['uuid'])
        self.h = tenant('h', self.top['uuid'])

        self.tenants = [
            self.top,
            self.a,
            self.b,
            self.c,
            self.d,
            self.e,
            self.f,
            self.g,
            self.h,
        ]

        self.tenant_dao = Mock()
        self.tenant_dao.list_.return_value = self.tenants

        self.tree = TenantTree(self.tenant_dao)

    def test_list_nodes(self):
        result = self.tree.list_nodes(self.f['uuid'])
        assert_that(result, contains_inanyorder(self.f['uuid']))

        result = self.tree.list_nodes(self.e['uuid'])
        assert_that(result, contains_inanyorder(self.e['uuid'], self.f['uuid']))

        result = self.tree.list_nodes(self.top['uuid'])
        assert_that(result, contains_inanyorder(*[t['uuid'] for t in self.tenants]))

        result = self.tree.list_nodes(self.a['uuid'])
        assert_that(
            result,
            contains_inanyorder(
                self.a['uuid'],
                self.b['uuid'],
                self.c['uuid'],
                self.d['uuid'],
                self.g['uuid'],
            ),
        )
