"""OS syscall boundary installed before any candidate code is executed."""
import ctypes
import errno
import resource


def lock_down():
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    lib = ctypes.CDLL('libseccomp.so.2', use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_rule_add.restype = ctypes.c_int
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_load.restype = ctypes.c_int
    ctx = lib.seccomp_init(0x00050000 | errno.EPERM)
    # No open, stat-by-path, networking, exec, fork, ptrace, process memory,
    # descriptor transfer, filesystem writes, mounts or signalling other processes.
    names = ['read','write','close','fstat','lseek','brk','mmap','mprotect',
             'munmap','mremap','madvise','futex','clock_gettime','gettimeofday',
             'getpid','gettid','getrusage','rt_sigaction','rt_sigprocmask',
             'rt_sigreturn','sigaltstack','setitimer','exit','exit_group']
    for name in names:
        number = lib.seccomp_syscall_resolve_name(name.encode())
        if number < 0 or lib.seccomp_rule_add(ctx, 0x7fff0000, number, 0):
            raise RuntimeError('seccomp rule failed: ' + name)
    if lib.seccomp_load(ctx):
        raise RuntimeError('seccomp load failed')
