# -*- coding: utf-8 -*-
# Copyright 2017-2018 The Wazo Authors  (see the AUTHORS file)
# SPDX-License-Identifier: GPL-3.0+

from hamcrest import (
    assert_that,
    has_entries,
)
from helpers.base import MockBackendTestCase


class TestMultiTenant(MockBackendTestCase):

    def test_given_user_in_new_tenant_when_create_user_then_creation_allowed(self):
        creator_user = self.client.users.new(username='creator', password='opensesame')
        auth_policy = self.client.policies.new(name='auth-allowed', acl_templates=['auth.#'])
        self.client.users.add_policy(creator_user['uuid'], auth_policy['uuid'])
        creator_client = self.new_auth_client(username='creator', password='opensesame')
        creator_token = creator_client.token.new(backend='wazo_user')
        creator_client.set_token(creator_token['token'])
        created_tenant = creator_client.tenants.new(name='created-tenant')
        creator_client.tenants.add_user(created_tenant['uuid'], creator_user['uuid'])

        created_user = creator_client.users.new(username='created-user', password='opensesame', tenant_uuid=created_tenant['uuid'])

        assert_that(created_user, has_entries(username='created-user'))