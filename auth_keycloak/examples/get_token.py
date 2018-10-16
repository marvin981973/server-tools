# -*- coding: utf-8 -*-

import requests
import click
from urlparse import urljoin
import sys
import json


UID = 'admin'
PWD = 'admin'
REALM = 'master'
DOMAIN = 'http://localhost:8080'
CLIENT_ID = 'odoo'
CLIENT_SECRET = '099d7d07-be3b-4bc6-b69e-b50ca5d0d864'
BASE_PATH = '/auth/realms/{realm}/protocol/openid-connect'
GET_TOKEN_PATH = BASE_PATH + '/token'
VALIDATE_PATH = GET_TOKEN_PATH + '/introspect'
USERINFO_PATH = BASE_PATH + '/userinfo'
# Watch out w/ official docs, they are wrong here
# https://issues.jboss.org/browse/KEYCLOAK-8615
USERS_PATH = '/auth/admin/realms/{realm}/users'
DATA_FILE = '/tmp/keycloak.json'


@click.command()
@click.option('--domain', default=DOMAIN)
@click.option('--realm', default=REALM)
@click.option(
    '--username',
    prompt='Username',
    help='Username to authenticate.',
    default=UID)
@click.option(
    '--password',
    prompt='Password',
    default=PWD)
@click.option(
    '--client_id',
    prompt='Client ID',
    help='Keycloak client ID.',
    default=CLIENT_ID)
@click.option(
    '--client_secret',
    prompt='Client secret',
    help='Keycloak client secret.',
    default=CLIENT_SECRET)
def get_token(**kw):
    """Retrieve auth token."""
    data = kw.copy()
    data['grant_type'] = 'password'
    token = _get_token(data)
    data['token'] = token
    with open(DATA_FILE, 'w') as ff:
        ff.write(json.dumps(data))
        click.echo('Saved to %s' % DATA_FILE)
    return token


def _get_token(data):
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    url = urljoin(data['domain'], GET_TOKEN_PATH.format(realm=data['realm']))
    click.echo('Calling %s' % url)
    click.echo(data)
    resp = requests.post(url, data=data, headers=headers)
    if not resp.ok:
        click.echo(resp.content)
        click.echo('Something went wrong. Quitting. ')
        sys.exit(0)
    click.echo('Access token:')
    click.echo(resp.json()['access_token'])
    return resp.json()['access_token']


if __name__ == '__main__':
    get_token()
