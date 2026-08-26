import storage

# This is safe only while the sketch owns CIRCUITPY: it reads code and
# reads/writes the N2YO cache.  When a computer mounts CIRCUITPY, remount it
# read-only and only read the cache; concurrent writes can cause Bad Things.
storage.remount("/", readonly=False, disable_concurrent_write_protection=True)
