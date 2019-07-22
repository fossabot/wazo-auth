# Copyright 2016-2019 The Wazo Authors  (see the AUTHORS file)
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from sqlalchemy import and_, exc
from .base import BaseDAO, PaginatorMixin
from . import filters
from ..models import (
    ExternalAuthConfig,
    ExternalAuthData,
    ExternalAuthType,
    Tenant,
    User,
    UserExternalAuth,
)
from ... import exceptions


class ExternalAuthDAO(filters.FilterMixin, PaginatorMixin, BaseDAO):

    search_filter = filters.external_auth_search_filter
    strict_filter = filters.external_auth_strict_filter
    column_map = {'type': ExternalAuthType.name}

    def count(self, user_uuid, **kwargs):
        filtered = kwargs.get('filtered')
        base_filter = ExternalAuthType.enabled is True

        if filtered is False:
            filter_ = base_filter
        else:
            search_filter = self.new_search_filter(**kwargs)
            strict_filter = self.new_strict_filter(**kwargs)
            filter_ = and_(base_filter, search_filter, strict_filter)

        with self.new_session() as s:
            return s.query(ExternalAuthType).filter(filter_).count()

    def create(self, user_uuid, auth_type, data):
        serialized_data = json.dumps(data)
        with self.new_session() as s:
            external_type = self._find_or_create_type(s, auth_type)
            external_data = ExternalAuthData(data=serialized_data)
            s.add(external_data)
            s.commit()
            user_external_auth = UserExternalAuth(
                user_uuid=str(user_uuid),
                external_auth_type_uuid=external_type.uuid,
                external_auth_data_uuid=external_data.uuid,
            )
            s.add(user_external_auth)
            try:
                s.commit()
            except exc.IntegrityError as e:
                if e.orig.pgcode in (
                    self._UNIQUE_CONSTRAINT_CODE,
                    self._FKEY_CONSTRAINT_CODE,
                ):
                    constraint = e.orig.diag.constraint_name
                    if constraint == 'auth_external_user_type_auth_constraint':
                        raise exceptions.ExternalAuthAlreadyExists(auth_type)
                    elif constraint == 'auth_user_external_auth_user_uuid_fkey':
                        raise exceptions.UnknownUserException(user_uuid)
                raise
            return data

    def create_config(self, auth_type, data, tenant_uuid):
        data = json.dumps(data)
        with self.new_session() as s:
            external_type = self._find_or_create_type(s, auth_type)
            external_data = ExternalAuthData(data=data)
            self._assert_tenant_exists(s, tenant_uuid)
            s.add(external_data)
            s.commit()
            external_auth_config = ExternalAuthConfig(
                data_uuid=external_data.uuid,
                tenant_uuid=tenant_uuid,
                type_uuid=external_type.uuid,
            )
            s.add(external_auth_config)
            try:
                s.commit()
            except exc.IntegrityError as e:
                if e.orig.pgcode in (self._UNIQUE_CONSTRAINT_CODE):
                    constraint = e.orig.diag.constraint_name
                    if constraint == 'auth_external_auth_config_pkey':
                        raise exceptions.ExternalAuthConfigAlreadyExists(auth_type)
                raise
            return data

    def delete(self, user_uuid, auth_type):
        with self.new_session() as s:
            type_ = self._find_type(s, auth_type)
            filter_ = and_(
                UserExternalAuth.user_uuid == str(user_uuid),
                UserExternalAuth.external_auth_type_uuid == type_.uuid,
            )

            nb_deleted = s.query(UserExternalAuth).filter(filter_).delete()
            if nb_deleted:
                return

            self._assert_user_exists(s, user_uuid)
            raise exceptions.UnknownExternalAuthException(auth_type)

    def delete_config(self, auth_type, tenant_uuid):
        with self.new_session() as s:
            type_ = self._find_type(s, auth_type)
            filter_ = and_(
                ExternalAuthConfig.type_uuid == type_.uuid,
                ExternalAuthConfig.tenant_uuid == tenant_uuid,
            )
            nb_deleted = s.query(ExternalAuthConfig).filter(filter_).delete()
            if nb_deleted:
                return

            raise exceptions.UnknownExternalAuthConfigException(auth_type)

    def enable_all(self, auth_types):
        with self.new_session() as s:
            query = s.query(ExternalAuthType.name, ExternalAuthType.enabled)
            all_types = {r.name: r.enabled for r in query.all()}

            for type_ in auth_types:
                if type_ in all_types:
                    continue
                s.add(ExternalAuthType(name=type_, enabled=True))

            for type_, enabled in all_types.items():
                if type_ in auth_types and enabled:
                    continue

                if type_ not in auth_types and not enabled:
                    continue

                filter_ = ExternalAuthType.name == type_
                value = type_ in auth_types and not enabled
                s.query(ExternalAuthType).filter(filter_).update({'enabled': value})

    def get(self, user_uuid, auth_type):
        filter_ = and_(
            UserExternalAuth.user_uuid == str(user_uuid),
            ExternalAuthType.name == auth_type,
        )

        with self.new_session() as s:
            data = (
                s.query(ExternalAuthData.data)
                .join(UserExternalAuth)
                .join(ExternalAuthType)
                .filter(filter_)
                .first()
            )

            if data:
                return json.loads(data.data)

            self._assert_type_exists(s, auth_type)
            self._assert_user_exists(s, user_uuid)
            raise exceptions.UnknownExternalAuthException(auth_type)

    def get_config(self, auth_type, tenant_uuid):
        with self.new_session() as s:
            try:
                external_auth_type = self._find_type(s, auth_type)
            except exceptions.UnknownExternalAuthTypeException:
                raise exceptions.ExternalAuthConfigNotFound(auth_type)

            result = (
                s.query(ExternalAuthData.data)
                .join(ExternalAuthConfig)
                .join(ExternalAuthType)
                .filter(
                    ExternalAuthType.name == external_auth_type.name,
                    ExternalAuthConfig.tenant_uuid == tenant_uuid,
                )
                .first()
            )

            if result:
                return json.loads(result.data)

            raise exceptions.UnknownExternalAuthConfigException(auth_type)

    def list_(self, user_uuid, **kwargs):
        base_filter = ExternalAuthType.enabled is True
        search_filter = self.new_search_filter(**kwargs)
        strict_filter = self.new_strict_filter(**kwargs)
        filter_ = and_(base_filter, search_filter, strict_filter)

        result = []

        with self.new_session() as s:
            query = s.query(ExternalAuthType).filter(filter_)
            query = self._paginator.update_query(query, **kwargs)
            result = [
                {'type': r.name, 'data': {}, 'enabled': False} for r in query.all()
            ]

            filter_ = and_(filter_, UserExternalAuth.user_uuid == str(user_uuid))
            query = (
                s.query(ExternalAuthType.name, ExternalAuthData.data)
                .select_from(UserExternalAuth)
                .join(ExternalAuthType)
                .join(ExternalAuthData)
                .filter(filter_)
            )
            for type_, data in query.all():
                for row in result:
                    if row['type'] != type_:
                        continue
                    row.update({'enabled': True, 'data': json.loads(data)})

        return result

    def update(self, user_uuid, auth_type, data):
        self.delete(user_uuid, auth_type)
        return self.create(user_uuid, auth_type, data)

    def update_config(self, auth_type, data, tenant_uuid):
        self.delete_config(auth_type, tenant_uuid)
        return self.create_config(auth_type, data, tenant_uuid)

    def _assert_tenant_exists(self, s, tenant_uuid):
        if s.query(Tenant).filter(Tenant.uuid == str(tenant_uuid)).count() == 0:
            raise exceptions.TenantParamException(tenant_uuid)

    def _assert_type_exists(self, s, auth_type):
        self._find_type(s, auth_type)

    def _assert_user_exists(self, s, user_uuid):
        if s.query(User).filter(User.uuid == str(user_uuid)).count() == 0:
            raise exceptions.UnknownUserException(user_uuid)

    def _find_type(self, s, auth_type):
        type_ = (
            s.query(ExternalAuthType).filter(ExternalAuthType.name == auth_type).first()
        )
        if type_:
            return type_
        raise exceptions.UnknownExternalAuthTypeException(auth_type)

    def _find_or_create_type(self, s, auth_type):
        try:
            type_ = self._find_type(s, auth_type)
        except exceptions.UnknownExternalAuthTypeException:
            type_ = ExternalAuthType(name=auth_type)
            s.add(type_)
        return type_
