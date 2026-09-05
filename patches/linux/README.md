# Linux host compatibility

The PID 1 test patch keeps Crashpad's cross-process credential checks but obtains
expected init ownership from `/proc/1` instead of assuming UID/GID zero. The kernel
reports unmapped host credentials as 65534 inside an unprivileged user namespace.
This patch changes a test expectation for that supported environment, not runtime
process inspection. The build additionally omits automatic build-tree rpaths so
unit binaries do not accidentally load the glibc 2.17 compiler sysroot under a
modern host loader, and marks linked stacks non-executable for current glibc.
