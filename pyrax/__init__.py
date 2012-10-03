#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os

import exceptions as exc
import rax_identity as _rax_identity
import version

import cf_wrapper.client as _cf
try:
    import clouddb as _cdb
    _USE_DB = True
except ImportError:
    _USE_DB = False
try:
    import clouddns as _cdns
    _USE_DNS = True
except ImportError:
    _USE_DNS = False
import cloudlb as _cloudlb
from keystoneclient.v2_0 import client as _ks_client
from novaclient.v1_1 import client as _cs_client

# These require Libcloud
#import rackspace_monitoring.providers as mon_providers
#import rackspace_monitoring.types as mon_types


# Default to the rax_identity class.
identity_class = _rax_identity.Identity
# Allow for different identity classes.
def set_identity_class(cls):
    global identity_class
    identity_class = cls

# This can be changed for unit testing or for other identity managers.
identity = identity_class()
# Initiate the services to None until we are authenticated.
cloudservers = None
cloudfiles = None
keystone = None
cloud_lbs = None
cloud_lb_node = None
cloud_lb_vip = None
cloud_dns = None
cloud_db = None
# Default region for all services. Can be individually overridden if needed
default_region = None
# Some services require a region. If the user doesn't specify one, use DFW.
FALLBACK_REGION = "DFW"
# Value to plug into the user-agent headers
USER_AGENT = "pyrax/%s" % version.version


def _require_auth(fnc):
    """Authentication decorator."""
    def _wrapped(*args, **kwargs):
        if not identity.authenticated:
            msg = "Authentication required before calling '%s'." % fnc.__name__
            raise exc.NotAuthenticated(msg)
        return fnc(*args, **kwargs)
    return _wrapped


def set_credentials(username, api_key, authenticate=True):
    """Set the username and api_key directly, and then try to authenticate."""
    identity.set_credentials(username=username, api_key=api_key, authenticate=authenticate)
    if identity.authenticated:
        connect_to_services()


def set_credential_file(cred_file, authenticate=True):
    """
    Read in the credentials from the supplied file path, and then try to
    authenticate. The file should be a standard config file in the format:

    [rackspace_cloud]
    username = myusername
    api_key = 1234567890abcdef

    """
    identity.set_credential_file(cred_file, authenticate=authenticate)
    if identity.authenticated:
        connect_to_services()


def clear_credentials():
    """De-authenticate by clearing all the names back to None."""
    global identity, cloudservers, cloudfiles, keystone, cloud_lbs, cloud_lb_node, cloud_lb_vip
    global cloud_dns, cloud_db, default_region
    identity = identity_class()
    cloudservers = None
    cloudfiles = None
    keystone = None
    cloud_lbs = None
    cloud_lb_node = None
    cloud_lb_vip = None
    cloud_dns = None
    cloud_db = None
    default_region = None


def set_default_region(region):
    global default_region
    default_region = region


def _make_agent_name(base):
    return "%s:%s" % (base, USER_AGENT)


@_require_auth
def connect_to_services():
    """Establish authenticated connections to the various cloud APIs."""
    connect_to_cloudservers()
    connect_to_cloudfiles()
    connect_to_keystone()
    connect_to_cloud_lbs()
    connect_to_cloud_dns()
    connect_to_cloud_db()


@_require_auth
def connect_to_cloudservers(region=None):
    global cloudservers
    if region is None:
        region = default_region or FALLBACK_REGION
    mgt_url = identity.services.get("compute", {}).get("endpoints", {}).get(region, {}).get("public_url")
    if not mgt_url:
        # Try the 'ALL' region
        mgt_url = identity.services.get("compute", {}).get("endpoints", {}).get("ALL", {}).get("public_url")
    cloudservers = _cs_client.Client(identity.username, identity.api_key, identity.tenant_name,
            identity.auth_endpoint, bypass_url=mgt_url, auth_system="rackspace",
            region_name=region, service_type="compute")
    cloudservers.client.USER_AGENT = _make_agent_name(cloudservers.client.USER_AGENT)


@_require_auth
def connect_to_cloudfiles(region=None):
    global cloudfiles
    if region is None:
        region = default_region or FALLBACK_REGION
    cf_url = identity.services.get("object_store", {}).get("endpoints", {}).get(region, {}).get("public_url")
    cdn_url = identity.services.get("object_cdn", {}).get("endpoints", {}).get(region, {}).get("public_url")
    opts = {"tenant_id": identity.tenant_name, "auth_token": identity.token, "endpoint_type": "publicURL",
            "tenant_name": identity.tenant_name, "object_storage_url": cf_url, "object_cdn_url": cdn_url,
            "region_name": region}
    cloudfiles = _cf.Client(identity.auth_endpoint, identity.username, identity.api_key,
            tenant_name=identity.tenant_name, preauthurl=cf_url, preauthtoken=identity.token,
            auth_version="2", os_options=opts)
    cloudfiles.user_agent = _make_agent_name(cloudfiles.user_agent)


@_require_auth
def connect_to_keystone():
    global keystone
    _ks_client.Client.USER_AGENT = _make_agent_name(_ks_client.Client.USER_AGENT)
    keystone = _ks_client.Client(token=identity.token, auth_url=identity.auth_endpoint,
            tenant_name=identity.tenant_name, username=identity.username, password=identity.api_key)


@_require_auth
def connect_to_cloud_lbs(region=None):
    global cloud_lbs, cloud_lb_node, cloud_lb_vip
    if region is None:
        region = default_region or FALLBACK_REGION
    _cloudlb.consts.USER_AGENT = _make_agent_name(_cloudlb.consts.USER_AGENT)
    _clb = _cloudlb.CloudLoadBalancer(identity.username, identity.api_key, region)
    cloud_lbs = _clb.loadbalancers
    cloud_lb_node = _cloudlb.Node
    cloud_lb_vip = _cloudlb.VirtualIP


@_require_auth
def connect_to_cloud_dns(region=None):
    if not _USE_DNS:
        return
    global cloud_dns
    if region is None:
        region = default_region or FALLBACK_REGION
    cloud_dns = _cdns.Connection(identity.username, identity.api_key)
    cloud_dns.user_agent = _make_agent_name(cloud_dns.user_agent)


@_require_auth
def connect_to_cloud_db(region=None):
    if not _USE_DB:
        return
    global cloud_db
    if region is None:
        region = default_region or FALLBACK_REGION
    _cdb.consts.USER_AGENT = _make_agent_name(_cdb.consts.USER_AGENT)
    cloud_db = _cdb.CloudDB(identity.username, identity.api_key, region)
    cloud_db.authenticate()


def _dev_only_auth():
    creds_file = os.path.expanduser("~/.rackspace_cloud_credentials")
    set_credential_file(creds_file)


if __name__ == "__main__":
    _dev_only_auth()

