XtremIO Cinder Driver for Liberty
=================================

This driver adds support for Glance generic caching in Liberty


XtremIO Block Storage driver configuration
------------------------------------------

Edit the `cinder.conf` file by adding the configuration below under
the `[DEFAULT]` section of the file in case of a single back end or
under a separate section in case of multiple back ends (for example
[XTREMIO_1]). The configuration file is usually located under the
following path `/etc/cinder/cinder.conf`.

Image service optimization
--------------------------

Enable image service optimization by setting the appropriate values for
 The following keys in `/etc/cinder/cinder.conf`.

    cinder_internal_tenant_project_id = 
    cinder_internal_tenant_user_id = 
    image_volume_cache_enabled = True
    image_volume_cache_max_size_gb = 0
    image_volume_cache_max_count = 0
    

Limit the number of copies (XtremIO snapshots) taken from each image cache.

    xtremio_volumes_per_glance_cache = 100

The default value is `100`. To use the cluster limit set to `0`.


Other versions of OpenStack
---------------------------
 * Kilo - https://github.com/emc-openstack/xtremio-cinder-driver/tree/kilo
 * Mitaka and Newton latest driver are inline within OpenStack main repository