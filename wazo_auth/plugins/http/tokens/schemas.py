# Copyright 2017-2019 The Wazo Authors  (see the AUTHORS file)
# SPDX-License-Identifier: GPL-3.0-or-later

from marshmallow import Schema, fields, validates_schema
from marshmallow.validate import Length, Range, OneOf
from marshmallow.exceptions import ValidationError


class TokenRequestSchema(Schema):
    backend = fields.String(missing='wazo_user')
    expiration = fields.Integer(validate=Range(min=1))
    access_type = fields.String(validate=OneOf(['online', 'offline']))
    client_id = fields.String(validate=Length(min=1, max=1024))
    refresh_token = fields.String()

    @validates_schema
    def check_access_type_usage(self, data):
        access_type = data.get('access_type')
        if access_type != 'offline':
            return

        refresh_token = data.get('refresh_token')
        if refresh_token:
            raise ValidationError(
                'cannot use the "access_type" "offline" with a refresh token'
            )

        client_id = data.get('client_id')
        if not client_id:
            raise ValidationError(
                '"client_id" must be specified when using "access_type" is "offline"'
            )

    @validates_schema
    def check_refresh_token_usage(self, data):
        refresh_token = data.get('refresh_token')
        if not refresh_token:
            return

        client_id = data.get('client_id')
        if not client_id:
            raise ValidationError(
                '"client_id" must be specified when using a "refresh_token"'
            )
