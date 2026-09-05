"""Inspect packaged PE imports without relying on a runner's installed VC runtime."""
from pathlib import Path
import pefile

CRT_DLLS = (
    'concrt140.dll', 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
    'msvcp140_atomic_wait.dll', 'msvcp140_codecvt_ids.dll', 'vccorlib140.dll',
    'vcruntime140.dll', 'vcruntime140_1.dll',
)
MINIMUM_CRT = (14, 34)
AMD64 = pefile.MACHINE_TYPE['IMAGE_FILE_MACHINE_AMD64']
I386 = pefile.MACHINE_TYPE['IMAGE_FILE_MACHINE_I386']
MAX_EXPORTS = 1_000_000
SYSTEM_DLLS = set('''advapi32 authz avicap32 avrt bcrypt bluetoothapis bthprops.cpl cfgmgr32 combase comctl32
comdlg32 crypt32 cryptbase cryptsp d2d1 d3d9 d3d11 d3d12 d3dcompiler_47 dbgcore dbghelp
dcomp dhcpcsvc dnsapi dwmapi dwrite dxcore dxgi dxva2 fltlib gdi32 gdi32full glu32
hid imagehlp imm32 iphlpapi kernel32 kernelbase mf mfplat mfreadwrite mmdevapi
mpr msacm32 msimg32 msvcrt ncrypt netapi32 normaliz ntdll odbc32 ole32 oleacc oleaut32
opengl32 pdh powrprof propsys psapi rasapi32 rpcrt4 secur32 sensapi setupapi shell32
shlwapi sspicli ucrtbase urlmon user32 userenv usp10 uxtheme version win32u windowscodecs
winhttp wininet winmm winnsi winscard winspool.drv wintrust wlanapi wldap32
winusb ws2_32 wtsapi32'''.split())
SYSTEM_DLLS = {name if '.' in name else name + '.dll' for name in SYSTEM_DLLS}


def version_bytes(data):
    with pefile.PE(data=data, fast_load=True) as pe:
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
        if not getattr(pe, 'VS_FIXEDFILEINFO', None):
            raise ValueError('PE file has no fixed version information')
        fixed = pe.VS_FIXEDFILEINFO[0]
        return (fixed.FileVersionMS >> 16, fixed.FileVersionMS & 65535,
                fixed.FileVersionLS >> 16, fixed.FileVersionLS & 65535)


def machine_bytes(data):
    with pefile.PE(data=data, fast_load=True) as pe:
        return pe.FILE_HEADER.Machine


def system_library(name):
    return name in SYSTEM_DLLS or name.startswith(('api-ms-win-', 'ext-ms-win-'))


def audit(root):
    root = Path(root)
    binaries = []
    providers = {}
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.suffix.lower() not in ('.exe', '.dll'):
            continue
        # Protobuf exports more symbols than pefile's default 8192 limit.
        # Parse all declared exports within a bound, then verify completeness.
        with pefile.PE(str(path), fast_load=True, max_symbol_exports=MAX_EXPORTS) as pe:
            machine = pe.FILE_HEADER.Machine
            # Upstream deliberately ships x86 Cygwin e2fsprogs helpers in
            # bin64. Keep their dependency graph separate from x64 QEMU.
            if machine not in (AMD64, I386):
                raise ValueError(f'Unsupported PE architecture: {path.relative_to(root)}')
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY[name] for name in (
                'IMAGE_DIRECTORY_ENTRY_IMPORT', 'IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT',
                'IMAGE_DIRECTORY_ENTRY_EXPORT')])
            imports = []
            for entry in [*getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []),
                          *getattr(pe, 'DIRECTORY_ENTRY_DELAY_IMPORT', [])]:
                imports.append((entry.dll.decode('ascii').lower(),
                                [symbol.name if symbol.name else symbol.ordinal for symbol in entry.imports]))
            exports = set()
            directory = getattr(pe, 'DIRECTORY_ENTRY_EXPORT', None)
            symbols = getattr(directory, 'symbols', [])
            if directory and (directory.struct.NumberOfNames > MAX_EXPORTS
                              or directory.struct.NumberOfFunctions > MAX_EXPORTS
                              or sum(symbol.name is not None for symbol in symbols)
                              != directory.struct.NumberOfNames):
                raise ValueError(f'Export directory was not completely parsed: {path.relative_to(root)}')
            for symbol in symbols:
                exports.add(symbol.ordinal)
                if symbol.name:
                    exports.add(symbol.name)
                if symbol.forwarder:
                    forwarded = symbol.forwarder.decode('ascii').rsplit('.', 1)[0].lower()
                    imports.append((forwarded if forwarded.endswith('.dll') else forwarded + '.dll', []))
            entry = {'path': path.relative_to(root).as_posix(), 'machine': machine,
                     'imports': imports, 'exports': exports,
                     'named_exports': directory.struct.NumberOfNames if directory else 0,
                     'parsed_export_records': len(symbols)}
            binaries.append(entry)
            providers.setdefault((path.name.lower(), machine), []).append(entry)
    if not binaries:
        raise ValueError('SDK contains no PE binaries')
    dependencies = []
    for binary in binaries:
        for library, symbols in binary['imports']:
            candidates = providers.get((library, binary['machine']), [])
            if candidates:
                available = set().union(*(candidate['exports'] for candidate in candidates))
                missing = [symbol for symbol in symbols if symbol not in available]
                if missing:
                    raise ValueError(f'{binary["path"]} imports absent symbols from {library}: {missing[:8]}')
                resolution = 'packaged'
            elif system_library(library):
                resolution = 'windows-system-or-api-set'
            else:
                raise ValueError(f'Unbundled non-system dependency: {binary["path"]} -> {library}')
            dependencies.append({'binary': binary['path'], 'dll': library, 'resolution': resolution,
                                 'architecture': 'x86_64' if binary['machine'] == AMD64 else 'x86'})
    runtime = []
    for name in CRT_DLLS:
        if not (root / name).is_file():
            raise ValueError(f'VC runtime must be next to the SDK entry executable: {name}')
        if machine_bytes((root / name).read_bytes()) != AMD64:
            raise ValueError(f'Entry executable runtime must be x64: {name}')
        if (name, AMD64) not in providers:
            raise ValueError(f'Required app-local VC runtime missing: {name}')
        for provider in providers[name, AMD64]:
            version = version_bytes((root / provider['path']).read_bytes())
            if version[:2] < MINIMUM_CRT:
                raise ValueError(f'{provider["path"]} runtime {version} is older than MSVC 14.34')
            runtime.append({'file': provider['path'], 'version': '.'.join(map(str, version))})
    return {'pe_binaries': len(binaries), 'dependency_edges': dependencies, 'vc_runtime': runtime,
            'export_directories': [{key: binary[key] for key in ('path', 'named_exports', 'parsed_export_records')}
                                   for binary in binaries if binary['named_exports']],
            'scope': 'PE imports, delay imports, export forwarders, and app-local VC runtime; no guest boot'}
