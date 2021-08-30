import logging

import sqlalchemy
import sqlalchemy.exc
from connexion import problem
from keycloak import KeycloakGetError
from werkzeug.exceptions import Forbidden
import dpath.util as dpath

from rhub.lab import model
from rhub.api import db, get_keycloak, get_vault
from rhub.auth import ADMIN_ROLE
from rhub.auth.keycloak import problem_from_keycloak_error


logger = logging.getLogger(__name__)


VAULT_PATH_PREFIX = 'kv/lab/region'
"""Vault path prefix to create new credentials in Vault."""


def list_regions(user):
    if get_keycloak().user_check_role(user, ADMIN_ROLE):
        regions = model.Region.query.all()
    else:
        user_groups = [group['id'] for group in get_keycloak().user_group_list(user)]
        regions = model.Region.query.filter(sqlalchemy.or_(
            model.Region.users_group.is_(None),
            model.Region.users_group.in_(user_groups),
            model.Region.owner_group.in_(user_groups),
        ))

    return [region.to_dict() for region in regions]


def create_region(body, user):
    try:
        owners_id = get_keycloak().group_create({
            'name': f'{body["name"]}-owners',
        })
        logger.info(f'Created owners group {owners_id}')
        body['owner_group'] = owners_id

        get_keycloak().group_user_add(user, owners_id)
        logger.info(f'Added {user} to owners group {owners_id}')

    except KeycloakGetError as e:
        logger.exception(e)
        return problem_from_keycloak_error(e)
    except Exception as e:
        logger.exception(e)
        return problem(500, 'Unknown Error',
                       f'Failed to create owner group in Keycloak, {e}')

    try:
        if body.get('users_group'):
            get_keycloak().group_get(body['users_group'])
    except KeycloakGetError as e:
        logger.exception(e)
        return problem(400, 'Users group does not exist',
                       f'Users group {body["users_group"]} does not exist in Keycloak, '
                       'you have to create group first or use existing group.')

    openstack_credentials = dpath.get(body, 'openstack/credentials')
    if not isinstance(openstack_credentials, str):
        openstack_credentials_path = f'{VAULT_PATH_PREFIX}/{body["name"]}/openstack'
        get_vault().write(openstack_credentials_path, openstack_credentials)
        dpath.set(body, 'openstack/credentials', openstack_credentials_path)

    satellite_credentials = dpath.get(body, 'satellite/credentials')
    if not isinstance(satellite_credentials, str):
        satellite_credentials_path = f'{VAULT_PATH_PREFIX}/{body["name"]}/satellite'
        get_vault().write(satellite_credentials_path, satellite_credentials)
        dpath.set(body, 'satellite/credentials', satellite_credentials_path)

    dns_server_key = dpath.get(body, 'dns_server/key')
    if not isinstance(dns_server_key, str):
        dns_server_key_path = f'{VAULT_PATH_PREFIX}/{body["name"]}/dns_server'
        get_vault().write(dns_server_key_path, dns_server_key)
        dpath.set(body, 'dns_server/key', dns_server_key_path)

    region = model.Region.from_dict(body)

    try:
        db.session.add(region)
        db.session.commit()
        logger.info(f'Region {region.name} (id {region.id}) created by user {user}')
    except sqlalchemy.exc.SQLAlchemyError:
        # If database transaction failed remove group in Keycloak.
        get_keycloak().group_delete(owners_id)
        raise

    return region.to_dict()


def get_region(region_id, user):
    region = model.Region.query.get(region_id)
    if not region:
        return problem(404, 'Not Found', f'Region {region_id} does not exist')

    if region.users_group is not None:
        if not get_keycloak().user_check_role(user, ADMIN_ROLE):
            if not get_keycloak().user_check_group_any(
                    user, [region.users_group, region.owner_group]):
                raise Forbidden("You don't have access to this region.")

    return region.to_dict()


def update_region(region_id, body, user):
    region = model.Region.query.get(region_id)
    if not region:
        return problem(404, 'Not Found', f'Region {region_id} does not exist')

    if not get_keycloak().user_check_role(user, ADMIN_ROLE):
        if not get_keycloak().user_check_group(user, region.owner_group):
            raise Forbidden("You don't have write access to this region.")

    try:
        if body.get('users_group'):
            get_keycloak().group_get(body['users_group'])
    except KeycloakGetError as e:
        logger.exception(e)
        return problem(400, 'Users group does not exist',
                       f'Users group {body["users_group"]} does not exist in Keycloak, '
                       'you have to create group first or use existing group.')

    if 'quota' in body:
        if body['quota']:
            if region.quota is None:
                region.quota = model.Quota(**body['quota'])
            else:
                for k, v in body['quota'].items():
                    setattr(region.quota, k, v)
        else:
            region.quota = None
        del body['quota']

    openstack_credentials = dpath.get(body, 'openstack/credentials',
                                      default=region.openstack_credentials)
    if not isinstance(openstack_credentials, str):
        get_vault().write(region.openstack_credentials, openstack_credentials)
        dpath.delete(body, 'openstack/credentials')

    satellite_credentials = dpath.get(body, 'satellite/credentials',
                                      default=region.satellite_credentials)
    if not isinstance(satellite_credentials, str):
        get_vault().write(region.satellite_credentials, satellite_credentials)
        dpath.delete(body, 'satellite/credentials')

    dns_server_key = dpath.get(body, 'dns_server/key',
                               default=region.dns_server_key)
    if not isinstance(dns_server_key, str):
        get_vault().write(region.dns_server_key, dns_server_key)
        dpath.delete(body, 'dns_server/key')

    region.update_from_dict(body)

    db.session.commit()
    logger.info(f'Region {region.name} (id {region.id}) updated by user {user}')

    return region.to_dict()


def delete_region(region_id, user):
    region = model.Region.query.get(region_id)
    if not region:
        return problem(404, 'Not Found', f'Region {region_id} does not exist')

    if not get_keycloak().user_check_role(user, ADMIN_ROLE):
        if not get_keycloak().user_check_group(user, region.owner_group):
            raise Forbidden("You don't have write access to this region.")

    db.session.delete(region)

    try:
        owner_group = get_keycloak().group_get(region.owner_group)
        get_keycloak().group_delete(owner_group['id'])
        logger.info(f'Deleted owners group {owner_group["id"]}')

    except KeycloakGetError as e:
        logger.exception(e)
        return problem_from_keycloak_error(e)
    except Exception as e:
        logger.exception(e)
        return problem(500, 'Unknown Error',
                       f'Failed to delete owner group in Keycloak, {e}')

    db.session.commit()
    logger.info(f'Region {region.name} (id {region.id}) deleted by user {user}')


def list_region_templates(region_id):
    raise NotImplementedError


def add_region_template(region_id, body):
    raise NotImplementedError


def delete_region_template(region_id, body):
    raise NotImplementedError
