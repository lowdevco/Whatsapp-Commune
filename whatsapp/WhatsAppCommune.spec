from PyInstaller.utils.hooks import collect_data_files

datas_list = [
    ('bulk/templates', 'bulk/templates'),
    ('bulk/static', 'bulk/static'),
] + collect_data_files('playwright_stealth')

binaries_list = [
    ('C:\\Python314\\python314.dll', '.'),
    ('C:\\Python314\\python314.dll', '_internal'),
]

a = Analysis(
    ['run_desktop.py'],
    pathex=[],
    binaries=binaries_list,
    datas=datas_list,
    hiddenimports=[
        'whatsapp.settings',
        'whatsapp.urls',
        'whatsapp.wsgi',
        'bulk.apps',
        'bulk.urls',
        'bulk.views',
        'bulk.models',
        'bulk.admin',
        'bulk.context_processors',
        'django.contrib.admin',
        'django.contrib.auth',
        'django.contrib.contenttypes',
        'django.contrib.sessions',
        'django.contrib.messages',
        'django.contrib.staticfiles',
        'django.db.backends.sqlite3',
        'waitress',
        'playwright',
        'playwright.sync_api',
        'google.genai',
        'pandas',
        'openpyxl',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'PyQt5', 'PyQt6', 'pyside6', 'notebook', 'IPython'],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WhatsApp Commune',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon_premium.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WhatsApp Commune',
)
