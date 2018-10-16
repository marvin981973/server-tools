# -*- coding: utf-8 -*-
# Copyright 2018 Camptocamp SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)
from odoo import fields, models, api, exceptions, _
import logging
import requests
try:
    from json.decoder import JSONDecodeError
except ImportError:
    # py2
    JSONDecodeError = ValueError

logger = logging.getLogger(__name__)


class KeycloakSyncMixin(models.TransientModel):
    """Synchronize Keycloak users mixin."""

    _name = 'auth.keycloak.sync.mixin'

    provider_id = fields.Many2one(
        string='Provider',
        comodel_name='auth.oauth.provider',
        required=True,
    )
    management_enabled = fields.Boolean(
        related='provider_id.users_management_enabled',
        readonly=True,
    )
    endpoint = fields.Char(
        related='provider_id.users_endpoint',
        readonly=True,
    )
    user = fields.Char(
        related='provider_id.superuser',
        readonly=True,
    )
    pwd = fields.Char(
        related='provider_id.superuser_pwd',
        readonly=True,
    )
    login_match_key = fields.Selection(
        selection=[
            # keycloak:odoo
            ('username:login', 'username'),
            ('email:partner_id.email', 'email'),
        ],
        help="Keycloak user field to match users' login.",
        default='username:login',
    )

    def _validate_setup(self):
        self.ensure_one()
        if not self.management_enabled:
            raise exceptions.UserError(
                _('Users management must be enabled on selected provider')
            )

    def _validate_response(self, resp, no_json=False):
        if not resp.ok:
            # TODO: do something better?
            raise resp.raise_for_status()
        if no_json:
            return None
        try:
            return resp.json()
        except JSONDecodeError:
            raise exceptions.UserError(
                _('Something went wrong. Please check logs.')
            )

    def _get_token(self):
        url = self.provider_id.validation_endpoint.replace('/introspect', '')
        logger.info('Calling %s' % url)
        headers = {'content-type': 'application/x-www-form-urlencoded'}
        data = {
            'username': self.user,
            'password': self.pwd,
            'grant_type': 'password',
            'client_id': self.provider_id.client_id,
            'client_secret': self.provider_id.client_secret,
        }
        resp = requests.post(url, data=data, headers=headers)
        self._validate_response(resp)
        return resp.json()['access_token']

    def _get_users(self, token, **params):
        logger.info('Calling %s' % self.endpoint)
        headers = {
            'Authorization': 'Bearer %s' % token,
        }
        resp = requests.get(self.endpoint, headers=headers, params=params)
        self._validate_response(resp)
        return resp.json()

    def _get_odoo_users(self, logins):
        odoo_key = self.login_match_key.split(':')[-1]
        domain = [
            ('oauth_uid', '=', False),
            (odoo_key, 'in', logins)
        ]
        return self.env['res.users'].search(domain)


class KeycloakSyncWiz(models.TransientModel):
    """Synchronize Keycloak users to Odoo.

    Keycloak auth works w/ its internal ID stored into `sub` key.
    Auth from Odoo will not work if Odoo users do not have this key stored.

    This wizard takes care of this
    so that your existing users will be able to login.

    This is not an issue for new users as they are sync'ed at signup.
    """

    _name = 'auth.keycloak.sync.wiz'
    _inherit = 'auth.keycloak.sync.mixin'

    @api.multi
    def button_sync(self):
        logger.info('Sync keycloak users START')
        self._validate_setup()
        token = self._get_token()
        users = self._get_users(token)
        logger.info('Found %s Keycloak users' % len(users))
        # map users by match key
        keycloak_key, odoo_key = self.login_match_key.split(':')
        logins_mapping = {
            x[keycloak_key]: x
            for x in users if x[keycloak_key]
        }
        logins = list(logins_mapping.keys())
        # find matching odoo users
        odoo_users = self._get_odoo_users(logins)
        logger.info('Matching %s Odoo users' % len(odoo_users))
        # update odoo users
        for user in odoo_users:
            # use `mapped` since we cann acces nested records
            keykloak_user = logins_mapping[user.mapped(odoo_key)[0]]
            # oh yeah, when you call `/userinfo` you get `sub` key
            # when you call `/users` you get `id` :S
            user.update({
                'oauth_uid': keykloak_user['id'],
                'oauth_provider_id': self.provider_id.id,
            })
        # open users' tree view
        action = self.env.ref('base.action_res_users').read()[0]
        action['domain'] = [('id', 'in', odoo_users.ids)]
        logger.info('Sync keycloak users STOP')
        return action


class KeycloakCreateWiz(models.TransientModel):
    """Export Odoo users to Keycloak."""

    _name = 'auth.keycloak.create.wiz'
    _inherit = 'auth.keycloak.sync.mixin'

    user_ids = fields.Many2many(
        comodel_name='res.users',
        default=lambda self: self.env.context.get('active_ids'),
    )

    def _validate_setup(self):
        super(KeycloakCreateWiz, self)._validate_setup()
        if not self.user_ids:
            raise exceptions.UserError(
                _('No user selected')
            )

    def _validate_response(self, resp, no_json=False):
        # When Keycloak detects a clash on non-unique values, like emails,
        # it raises:
        # `HTTPError: 409 Client Error: Conflict for url: `
        # http://keycloak:8080/auth/admin/realms/master/users
        if resp.status_code == 409:
            raise exceptions.UserError(_(
                'Conflict on user values. '
                'Please verify that all values supposed to be unique '
                'are really unique. For instance: email.'
            ))
        super(KeycloakCreateWiz, self)._validate_response(
            resp, no_json=no_json)

    def _get_or_create_user(self, token, odoo_user):
        odoo_key = self.login_match_key.split(':')[1]
        keycloak_user = self._get_users(
            token, search=odoo_user.mapped(odoo_key)[0])
        if keycloak_user:
            if len(keycloak_user) > 1:
                # do something
                pass
            return keycloak_user[0]
        else:
            values = self._create_user_values(odoo_user)
            keycloak_user = self._create_user(token, **values)
        return keycloak_user

    def _create_user_values(self, odoo_user):
        values = {
            'username': odoo_user.login,
            'email': odoo_user.email,
        }
        if 'firstname' in odoo_user.partner_id:
            # partner_firstname installed
            firstname = odoo_user.partner_id.firstname
            lastname = odoo_user.partner_id.lastname
        else:
            # yeah, I know, it's not perfect... you can override it ;)
            firstname, lastname = odoo_user.name.split(' ')
        values.update({
            'firstName': firstname,
            'lastName': lastname,
        })
        logger.debug('CREATE using values %s' % str(values))
        return values

    def _create_user(self, token, **data):
        logger.info('CREATE Calling %s' % self.endpoint)
        headers = {
            'Authorization': 'Bearer %s' % token,
        }
        # TODO: what to do w/ credentials?
        # Shall we just rely on Keycloak sending out a reset password link?
        # Shall we enforce a dummy pwd and enable "change after 1st login"?
        resp = requests.post(self.endpoint, headers=headers, json=data)
        self._validate_response(resp, no_json=True)
        return self._get_users(token, search=data['username'])[0]

    @api.multi
    def button_create_user(self):
        logger.debug('Create keycloak user START')
        self._validate_setup()
        token = self._get_token()
        logger.info(
            'Creating users for %s' % ','.join(self.user_ids.mapped('login'))
        )
        for user in self.user_ids:
            if user.oauth_uid:
                # already sync'ed somewhere else
                continue
            keycloak_user = self._get_or_create_user(token, user)
            user.update({
                'oauth_uid': keycloak_user['id'],
                'oauth_provider_id': self.provider_id.id,
            })
        action = self.env.ref('base.action_res_users').read()[0]
        action['domain'] = [('id', 'in', self.user_ids.ids)]
        logger.debug('Sync keycloak users STOP')
        return action
