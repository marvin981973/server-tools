# -*- coding: utf-8 -*-

import requests
import click
from urlparse import urljoin
import os
import sys
import json
from get_token import (
    DATA_FILE, VALIDATE_PATH,
    USERINFO_PATH, USERS_PATH,
    get_token
)


def _read_data():
    if not os.path.isfile(DATA_FILE):
        click.echo('You must run `get_token` before.')
        sys.exit(0)
    with open(DATA_FILE, 'r') as ff:
        return json.loads(ff.read())


@click.group()
@click.pass_context
def cli(ctx, **kw):
    ctx.params.update(_read_data())


@cli.command()
@click.pass_context
def user_info(ctx, **kw):
    """Retrieve user info."""
    params = ctx.parent.params
    url = urljoin(
        params['domain'], USERINFO_PATH.format(realm=params['realm'])
    )
    click.echo('Calling %s' % url)
    headers = {
        'Authorization': 'Bearer %s' % params['token'],
    }
    resp = requests.get(url, headers=headers)
    if not resp.ok:
        click.echo(resp.content)
        click.echo('Something went wrong. Quitting. ')
        sys.exit(0)
    click.echo('User info:')
    click.echo(resp.json())
    return resp.json()


@cli.command()
@click.option(
    '--search',
    help='Search string, see API.',
)
@click.pass_context
def get_users(ctx, search=None, **kw):
    """Retrieve users info."""
    params = ctx.parent.params
    url = urljoin(
        params['domain'],
        USERS_PATH.format(realm=params['realm'])
    )
    if search:
        url += '?search={}'.format(search)
    click.echo('Calling %s' % url)
    headers = {
        'Authorization': 'Bearer %s' % params['token'],
    }

    resp = requests.get(url, headers=headers)
    if not resp.ok:
        click.echo('Something went wrong. Quitting. ')
        click.echo(resp.content)
        if resp.reason:
            click.echo(resp.reason)
        sys.exit(0)
    click.echo('User info:')
    click.echo(resp.json())
    return resp.json()


@cli.command()
@click.option(
    '--username',
    required=True
)
@click.option(
    '--values',
    help='Values mapping like "key:value;key1:value1", see API.',
)
@click.pass_context
def create_user(ctx, username, values=None, **kw):
    """Create user."""
    params = ctx.parent.params
    url = urljoin(
        params['domain'],
        USERS_PATH.format(realm=params['realm'])
    )
    data = {
        'username': username,
        'enabled': True,
        'email': username + '@test.com',
        'emailVerified': True,
    }
    if values:
        for pair in values.split(';'):
            data[pair.split(':')[0]] = pair.split(':')[1]

    click.echo('Calling %s' % url)
    headers = {
        'Authorization': 'Bearer %s' % params['token'],
    }
    print('Sending', data)
    resp = requests.post(url, headers=headers, json=data)
    if not resp.ok:
        click.echo('Something went wrong. Quitting. ')
        click.echo(resp.content)
        if resp.reason:
            click.echo(resp.reason)
        sys.exit(0)
    # crate user does not give back any value :(
    return resp.ok


@cli.command()
@click.pass_context
def validate_token(ctx, **kw):
    """Retrieve user info."""
    params = ctx.parent.params
    if not params:
        # invoked via context
        params = _read_data()
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    data = {
        'token': params['token']
    }
    url = urljoin(
        params['domain'], VALIDATE_PATH.format(realm=params['realm'])
    )
    click.echo('Calling %s' % url)
    resp = requests.post(
        url,
        data=data,
        auth=(params['client_id'], params['client_secret']),
        headers=headers,
    )
    if not resp.ok:
        click.echo(resp.content)
        click.echo('Something went wrong. Quitting. ')
        sys.exit(0)
    result = resp.json()
    if not result.get('active'):
        # token expired
        click.echo('Token expired, running get token again...')
        ctx.invoke(get_token)
        ctx.forward(validate_token)
    click.echo(result)
    return resp.json()


if __name__ == '__main__':
    cli()
