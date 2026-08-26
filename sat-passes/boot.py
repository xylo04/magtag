import storage

# This is safe only while the sketch owns CIRCUITPY: it reads code and
# reads/writes the N2YO cache.  When a computer mounts CIRCUITPY, you should
# either only read the cache file, or remount read-only for the sketch. Concurrent
# writes can cause Bad Things.
# https://docs.circuitpython.org/en/stable/shared-bindings/storage/#storage.remount
storage.remount("/", readonly=False, disable_concurrent_write_protection=True)
