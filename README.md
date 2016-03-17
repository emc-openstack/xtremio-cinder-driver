Xtremio Cinder Driver for Kilo
==============================

This is a driver with Glance caching support for Kilo

XtremIO Block Storage driver configuration
------------------------------------------

Edit the `cinder.conf` file by adding the configuration below under
the `[DEFAULT]` section of the file in case of a single back end or
under a separate section in case of multiple back ends (for example
[XTREMIO]). The configuration file is usually located under the
following path `/etc/cinder/cinder.conf`.

Image service optimization
--------------------------

Enable image image service optimization.

    cache_images = True

The default is `False`.


Limit the number of copies (XtremIO snapshots) taken from each image cache.

    xtremio_volumes_per_glance_cache = 100

The default value is `100`. A value of `0` ignores the limit and defers to
the array maximum as the effective limit.
