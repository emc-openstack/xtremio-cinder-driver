# Copyright (c) 2012 - 2014 EMC Corporation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""
Driver for EMC XtremIO Storage.
supported XtremIO version 2.4 and up

1.0.0 - initial release
1.0.1 - enable volume extend
1.0.2 - added FC support, improved error handling
1.0.3 - update logging level, add translation
"""

import base64
import json
import random
import string
import urllib
import urllib2

from cinder import exception
from cinder.openstack.common.gettextutils import _
from cinder.openstack.common import log as logging
from cinder.volume import driver
from cinder.volume.drivers.san import san


LOG = logging.getLogger(__name__)

random = random.Random()


class XtremIOVolumeDriver(san.SanDriver):
    """Executes commands relating to Volumes."""

    VERSION = '1.0.3'
    driver_name = 'XtremIO'
    MIN_XMS_VERSION = [2, 4, 0]

    def __init__(self, *args, **kwargs):
        super(XtremIOVolumeDriver, self).__init__(*args, **kwargs)
        self.base64_auth = (base64.encodestring('%s:%s' %
                            (self.configuration.san_login,
                            self.configuration.san_password))
                            .replace('\n', ''))
        self.base_url = ('https://%s/api/json/types' %
                         self.configuration.san_ip)
        self.protocol = None
        self.backend_name = (self.configuration.safe_get(
                             'volume_backend_name') or
                             self.driver_name)

    def req(self, object_type='volumes', request_typ='GET', data=None,
            name=None, idx=None):
        if name and idx:
            LOG.error(_("req can't handle both name and index"))
            raise ValueError("can't handle both name and idx")

        url = '%s/%s' % (self.base_url, object_type)
        key = None
        if name:
            url = '%s?%s' % (url, urllib.urlencode({'name': name}))
            key = name
        elif idx:
            url = '%s/%d' % (url, idx)
            key = str(idx)
        if data and request_typ == 'GET':
            url + '?' + urllib.urlencode(data)
            request = urllib2.Request(url)
        elif data:
            LOG.debug('data: %s', json.dumps(data))
            request = urllib2.Request(url, json.dumps(data))
        else:
            request = urllib2.Request(url)
        LOG.debug('quering url: %s', url)
        request.get_method = lambda: request_typ
        request.add_header("Authorization", "Basic %s" % (self.base64_auth,))
        try:
            response = urllib2.urlopen(request)
        except (urllib2.HTTPError,) as exc:
            if exc.code == 400 and hasattr(exc, 'read'):
                error = json.load(exc)
                if error['message'].endswith('obj_not_found'):
                    LOG.warning(_("object %(key)s of type %(typ)s not found"),
                                {'key': key, 'typ': object_type})
                    raise exception.NotFound()
                elif error['message'] == 'vol_obj_name_not_unique':
                    LOG.error(_("can't create 2 volumes with the same name"))
                    raise (exception
                           .InvalidVolumeMetadata
                           ('Volume by this name already exists'))
            LOG.error(_('Bad response from XMS\n%s'), exc.read())
            raise
        if response.code >= 300:
            LOG.error(_('bad API response, %s'), response.msg)
            raise exception.VolumeBackendAPIException(
                data='bad response from XMS got http code %d, %s' %
                (response.code, response.msg))
        str_result = response.read()
        if str_result:
            try:
                return json.loads(str_result)
            except Exception:
                LOG.exception(_('quering %(typ)s, %(req)s failed to '
                                'parse result, return value = %(res)s'),
                              {'typ': object_type,
                               'req': request_typ,
                               'res': str_result})

    def _obj_from_result(self, res):
        typ, idx = res['links'][0]['href'].split('/')[-2:]
        return self.req(typ, 'GET', idx=int(idx))['content']

    def check_for_setup_error(self):
        sys = self.req('clusters', idx=1)['content']
        ver = [int(n) for n in sys['sys-sw-version'].split('-')[0].split('.')]
        if ver < self.MIN_XMS_VERSION:
            LOG.error(_('Invalid XtremIO version %s'), sys['sys-sw-version'])
            raise (exception.
                   VolumeBackendAPIException
                   ('Invalid XtremIO version, version 2.4 or up is required'))
        else:
            LOG.info(_('XtremIO SW version %s'), sys['sys-sw-version'])

    def create_volume(self, volume):
        "Creates a volume"
        data = {'vol-name': volume['id'],
                'vol-size': str(volume['size']) + 'g'
                }

        self.req('volumes', 'POST', data)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        data = {'snap-vol-name': volume['id'],
                'ancestor-vol-id': snapshot.id}

        self.req('snapshots', 'POST', data)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        data = {'snap-vol-name': volume['id'],
                'ancestor-vol-id': src_vref['id']}

        self.req('snapshots', 'POST', data)

    def delete_volume(self, volume):
        """Deletes a volume."""
        try:
            self.req('volumes', 'DELETE', name=volume['id'])
        except exception.NotFound:
            LOG.warning(_("delete failed, volume %s doesn't exists"),
                        volume['id'])

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        data = {'snap-vol-name': snapshot.id,
                'ancestor-vol-id': snapshot.volume_id}

        self.req('snapshots', 'POST', data)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        try:
            self.req('volumes', 'DELETE', name=snapshot.id)
        except exception.NotFound:
            LOG.warning(_("delete failed, snapshot %s doesn't exists"),
                        snapshot.id)

    def _update_volume_stats(self):
        self._stats = {'volume_backend_name': self.backend_name,
                       'vendor_name': 'EMC',
                       'driver_version': self.VERSION,
                       'storage_protocol': self.protocol,
                       'total_capacity_gb': 'infinite',
                       'free_capacity_gb': 'infinite',
                       'reserved_percentage': 0,
                       'QoS_support': False}

    def get_volume_stats(self, refresh=False):
        """Get volume stats.
        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._update_volume_stats()
        return self._stats

    def extend_volume(self, volume, new_size):
        """Extend an existing volume's size."""
        data = {'vol-size': str(new_size) + 'g'}
        self.req('volumes', 'PUT', data, name=volume['id'])

    def ensure_export(self, context, volume):
        "Driver entry point to get the export info for an existing volume."
        pass

    def create_export(self, context, volume):
        """Driver entry point to get the export info for a new volume."""
        pass

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume."""
        pass

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector"""
        try:
            ig = self.req('initiator-groups',
                          name=self._get_ig(connector))['content']
            tg = self.req('target-groups', name='Default')['content']
            vol = self.req('volumes', name=volume['id'])['content']

            lm_name = '%s_%s_%s' % (str(vol['index']),
                                    str(ig['index']) if ig else 'any',
                                    str(tg['index']))
            LOG.info(_('removing lun map %s'), lm_name)
            self.req('lun-maps', 'DELETE', name=lm_name)
        except exception.NotFound:
            LOG.warning(_("terminate_connection: object not found"))

    def _find_lunmap(self, ig_name, vol_name):
        for ig_link in self.req('lun-maps')['lun-maps']:
            idx = ig_link['href'].split('/')[-1]
            lm = self.req('lun-maps', idx=int(idx))['content']
            if lm['ig-name'] == ig_name and lm['vol-name'] == vol_name:
                return lm

    def _get_password(self):
        return ''.join(random.choice(string.ascii_uppercase + string.digits)
                       for _ in range(12))

    def create_lun_map(self, volume, ig):
        try:
            res = self.req('lun-maps', 'POST', {'ig-id': ig['ig-id'][2],
                                                'vol-id': volume['id']})
            lunmap = self._obj_from_result(res)
            LOG.info(_('created lunmap\n%s'), lunmap)
        except urllib2.HTTPError as exc:
            if exc.code == 400:
                error = json.load(exc)
                if 'already_mapped' in error.message:
                    LOG.info(_('volume already mapped,'
                               ' trying to retrieve it %(ig)s, %(vol)d'),
                             {'ig': ig['ig-id'][1], 'vol': volume['id']})
                    lunmap = self._find_lunmap(ig['ig-id'][1], volume['id'])
                elif error.message == 'vol_obj_not_found':
                    LOG.error(_("Can't find volume to map %s"), volume['id'])
                    raise exception.InvalidVolume("Can't find volume to map")
                else:
                    raise
            else:
                raise
        return lunmap

    def _get_ig(self, connector):
        raise NotImplementedError()


class XtremIOISCSIDriver(XtremIOVolumeDriver, driver.ISCSIDriver):
    """Executes commands relating to ISCSI volumes.

    We make use of model provider properties as follows:

    ``provider_location``
      if present, contains the iSCSI target information in the same
      format as an ietadm discovery
      i.e. '<ip>:<port>,<portal> <target IQN>'

    ``provider_auth``
      if present, contains a space-separated triple:
      '<auth method> <auth username> <auth password>'.
      `CHAP` is the only auth_method in use at the moment.
    """
    driver_name = 'XtremIO_ISCSI'

    def __init__(self, *args, **kwargs):
        super(XtremIOISCSIDriver, self).__init__(*args, **kwargs)
        self.protocol = 'iSCSI'

    def initialize_connection(self, volume, connector):
        #FIXME(shay-halsband): query the cluster index instead of using
        #the 1st one
        sys = self.req('clusters', 'GET', idx=1)['content']
        use_chap = (sys.get('chap-authentication-mode', 'disabled') !=
                    'disabled')
        dicovery_chap = (sys.get('chap-discovery-mode', 'disabled') !=
                         'disabled')
        initiator = self._get_initiator(connector)
        try:
            # check if the IG already exists
            ig = self.req('initiator-groups', 'GET',
                          name=self._get_ig(connector))['content']
        except exception.NotFound:
            #create an initiator group to hold the the initiator
            data = {'ig-name': self._get_ig(connector)}
            self.req('initiator-groups', 'POST', data)
            ig = self.req('initiator-groups',
                          name=self._get_ig(connector))['content']
        try:
            init = self.req('initiators', 'GET',
                            name=initiator)['content']
            if use_chap:
                chap_passwd = init['chap-authentication-initiator-'
                                   'password']
                #delete the initiator to create a new one with password
                if not chap_passwd:
                    LOG.info(_('initiator has no password while using chap,'
                             'removing it'))
                    self.req('initiators', 'DELETE', name=initiator)
                    # check if the initiator already exists
                    raise exception.NotFound()
        except exception.NotFound:
            #create an initiator
            data = {'initiator-name': initiator,
                    'ig-id': initiator,
                    'port-address': initiator}
            if use_chap:
                data['initiator-authentication-user-name'] = 'chap_user'
                chap_passwd = self._get_password()
                data['initiator-authentication-password'] = chap_passwd
            if dicovery_chap:
                data['initiator-discovery-user-name'] = 'chap_user'
                data['initiator-discovery-'
                     'password'] = self._get_password()
            self.req('initiators', 'POST', data)
        #lun mappping
        lunmap = self.create_lun_map(volume, ig)

        properties = self._get_iscsi_properties(lunmap)

        if use_chap:
            properties['auth_method'] = 'CHAP'
            properties['auth_username'] = 'chap_user'
            properties['auth_password'] = chap_passwd

        LOG.debug('init conn params:\n%s', properties)
        return {
            'driver_volume_type': 'iscsi',
            'data': properties
        }

    def _get_iscsi_properties(self, lunmap):
        """Gets iscsi configuration
        :target_discovered:    boolean indicating whether discovery was used
        :target_iqn:    the IQN of the iSCSI target
        :target_portal:    the portal of the iSCSI target
        :target_lun:    the lun of the iSCSI target
        :volume_id:    the id of the volume (currently used by xen)
        :auth_method:, :auth_username:, :auth_password:
            the authentication details. Right now, either auth_method is not
            present meaning no authentication, or auth_method == `CHAP`
            meaning use CHAP with the specified credentials.
        :access_mode:    the volume access mode allow client used
                         ('rw' or 'ro' currently supported)
        """
        iscsi_portals = [t['name'] for t in self.req('iscsi-portals', 'GET')
                         ['iscsi-portals']]
        #get a random portal
        portal_name = random.choice(iscsi_portals)
        portal = self.req('iscsi-portals', 'GET',
                          name=portal_name)['content']
        ip, mask = portal['ip-addr'].split('/')
        properties = {'target_discovered': False,
                      'target_iqn': portal['port-address'],
                      'target_lun': lunmap['lun'],
                      'target_portal': '%s:%d' % (ip, portal['ip-port']),
                      'access_mode': 'rw'}
        return properties

    def _get_initiator(self, connector):
        return connector['initiator']

    def _get_ig(self, connector):
        return connector['initiator']


class XtremIOFibreChannelDriver(XtremIOVolumeDriver,
                                driver.FibreChannelDriver):

    def __init__(self, *args, **kwargs):
        super(XtremIOFibreChannelDriver, self).__init__(*args, **kwargs)
        self.protocol = 'FC'

    def get_targets(self):
        if not hasattr(self, '_targets'):
            target_list = self.req('targets')["targets"]
            targets = [self.req('targets', name=target['name'])['content']
                       for target in target_list if '-fc' in target['name']]
            self._targets = [target['port-address'].replace(':', '')
                             for target in targets
                             if target['port-state'] == 'up']
        return self._targets

    def initialize_connection(self, volume, connector):
        initiators = self._get_initiator(connector)
        ig_name = self._get_ig(connector)
        # get or create initiator group
        try:
            # check if the IG already exists
            ig = self.req('initiator-groups', 'GET', name=ig_name)['content']
        except exception.NotFound:
            #create an initiator group to hold the the initiator
            data = {'ig-name': ig_name}
            self.req('initiator-groups', 'POST', data)
            ig = self.req('initiator-groups', name=ig_name)['content']
        # get or create all initiators
        for initiator in initiators:
            try:
                self.req('initiators', name=initiator)['content']
            except exception.NotFound:
                #create an initiator
                data = {'initiator-name': initiator,
                        'ig-id': ig['name'],
                        'port-address': initiator}
                self.req('initiators', 'POST', data)

        lunmap = self.create_lun_map(volume, ig)
        return {'driver_volume_type': 'fibre_channel',
                'data': {
                    'target_discovered': True,
                    'target_lun': lunmap['lun'],
                    'target_wwn': self.get_targets(),
                    'access_mode': 'rw'}}

    def _get_initiator(self, connector):
        return connector['wwpns']

    def _get_ig(self, connector):
        return connector['host']
