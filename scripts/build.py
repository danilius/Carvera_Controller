#!/usr/bin/python3
from __future__ import annotations

import argparse
import logging
import re
import shutil
import subprocess
import sys
import os
import platform
import toml
from glob import glob
from pathlib import Path

import PyInstaller.__main__
import pyinstaller_versionfile
from ruamel.yaml import YAML

from update_translations import compile_mo

logger = logging.getLogger(__name__)

# ------ Build config ------
APP_NAME = "Carvera-Controller-Community"
PACKAGE_NAME = "carveracontroller"
ASSETS_FOLDER = "packaging_assets"

# ------ Versionfile info ------
COMPANY_NAME = "Carvera-Community"
FILE_DESCRIPTION = APP_NAME
INTERNAL_NAME = APP_NAME
LEGAL_COPYRIGHT = "GNU General Public License v2.0"
PRODUCT_NAME = APP_NAME


# ------ Build paths ------
BUILD_PATH = Path(__file__).parent.resolve()
ROOT_PATH = BUILD_PATH.parent.resolve()
PROJECT_PATH = BUILD_PATH.parent.joinpath(PACKAGE_NAME).resolve()
PACKAGE_PATH = PROJECT_PATH.resolve()
ROOT_ASSETS_PATH = ROOT_PATH.joinpath(ASSETS_FOLDER).resolve()


def build_pyinstaller_args(
    os: str,
    output_filename: str,
    versionfile_path: Path | None = None,
) -> list[str]:
    logger.info("Build Pyinstaller args.")
    build_args = []
    script_entrypoint = f"{PACKAGE_NAME}/__main__.py"

    logger.info(f"entrypoint: {script_entrypoint}")
    build_args += [script_entrypoint]

    logger.info(f"Path to search for imports: {PACKAGE_PATH}")
    build_args += ["-p", f"{PACKAGE_PATH}"]

    logger.info(f"Spec file path: {BUILD_PATH}")
    build_args += ["--specpath", f"{BUILD_PATH}"]

    logger.info(f"Output exe filename: {output_filename}")
    build_args += ["-n", output_filename]

    if os == "macos":
        logger.info(f"Output file icon: {ROOT_ASSETS_PATH.joinpath('icon-src.icns')}")
        build_args += ["--icon", f"{ROOT_ASSETS_PATH.joinpath('icon-src.icns')}"]
    if os == "windows":
        logger.info("Build option: onefile")
        build_args += ["--onefile"]
        logger.info(f"Output file icon: {ROOT_ASSETS_PATH.joinpath('icon-src.ico')}")
        build_args += ["--icon", f"{ROOT_ASSETS_PATH.joinpath('icon-src.ico')}"]
    else:
        logger.info(f"Output file icon: {ROOT_ASSETS_PATH.joinpath('icon-src.png')}")
        build_args += ["--icon", f"{ROOT_ASSETS_PATH.joinpath('icon-src.png')}"]

    logger.info(f"Add bundled package assets: {PACKAGE_PATH}")
    build_args += ["--add-data", f"{PACKAGE_PATH}:carveracontroller"]

    logger.info("Build options: noconsole, noconfirm, noupx, clean")
    build_args += [
        "--noconsole",
        # "--debug=all",  # debug output toggle
        "--noconfirm",
        "--noupx",  # Not sure if the false positive AV hits are worth it
        "--clean",
        "--log-level=INFO",
    ]

    if versionfile_path is not None:
        logger.info(f"Versionfile path: {versionfile_path}")
        build_args += ["--version-file", f"{versionfile_path}"]

    print(" ".join(build_args))
    return build_args


def run_pyinstaller(build_args: list[str]) -> None:
    PyInstaller.__main__.run(build_args)


def generate_versionfile(package_version: str, output_filename: str) -> Path:
    logger.info("Generate versionfile.txt.")
    versionfile_path = BUILD_PATH.joinpath("versionfile.txt")
    pyinstaller_versionfile.create_versionfile(
        output_file=versionfile_path,
        version=package_version,
        company_name=COMPANY_NAME,
        file_description=FILE_DESCRIPTION,
        internal_name=INTERNAL_NAME,
        legal_copyright=LEGAL_COPYRIGHT,
        original_filename=f"{output_filename}.exe",
        product_name=PRODUCT_NAME,
    )

    return versionfile_path


def run_appimage_builder(package_version: str)-> None:
    revise_appimage_definition(package_version)
    command = f"appimage-builder --recipe {ROOT_ASSETS_PATH}/AppImageBuilder.yml"
    result = subprocess.run(command, shell=True, capture_output=False, text=True)
    if result.returncode != 0:
        logger.error(f"Error executing command: {command}")
        logger.error(f"stderr: {result.stderr}")
        sys.exit(result.returncode)


def remove_shared_libraries(freeze_dir, *filename_patterns):
    for pattern in filename_patterns:
        for file_path in glob(os.path.join(freeze_dir, pattern)):
            logger.info(f"Removing {file_path}")
            os.remove(file_path)


def revise_appimage_definition(package_version: str):
    yaml = YAML()
    with open(f"{ROOT_ASSETS_PATH}/AppImageBuilder-template.yml") as file:
        appimage_def = yaml.load(file)

    # revise definition to current system arch
    appimage_def["AppImage"]["arch"] = platform.machine()

    # version
    appimage_def["AppDir"]["app_info"]["version"] = package_version

    with open(f"{ROOT_ASSETS_PATH}/AppImageBuilder.yml", 'wb') as file:
        yaml.dump(appimage_def, file)


def fix_macos_version_string(version)-> None:
    command = f"plutil -replace CFBundleShortVersionString -string {version} dist/*.app/Contents/Info.plist"
    result = subprocess.run(command, shell=True, capture_output=False, text=True)
    if result.returncode != 0:
        logger.error(f"Error executing command: {command}")
        logger.error(f"stderr: {result.stderr}")
        sys.exit(result.returncode)


def codegen_version_string(package_version: str, project_path: str, root_path: str)-> None:
    # Update the __version__.py file used by the project
    with open(project_path.joinpath("__version__.py").resolve(), "w") as f:
        f.write(f"__version__ = '{package_version}'\n")
    
    # Update the value of `version` in` pyproject.toml
    pyproject_path = root_path.joinpath("pyproject.toml").resolve()
    data = toml.load(pyproject_path)
    if "tool" not in data or "poetry" not in data["tool"]:
        raise ValueError("[tool.poetry] section not found in pyproject.toml")
    data["tool"]["poetry"]["version"] = package_version
    with open(pyproject_path, "w", encoding="utf-8") as f:
        toml.dump(data, f)


def backup_codegen_files(root_path, project_path):
    backup_dir = Path('scripts/backup')
    files_to_backup = [
        Path(root_path, 'pyproject.toml'),
        Path(project_path, '__version__.py')
    ]
    backup_dir.mkdir(parents=True, exist_ok=True)
    for file_path in files_to_backup:
        if file_path.exists():
            shutil.copy2(file_path, backup_dir / file_path.name)
        else:
            print(f"File not found: {file_path}")


def restore_codegen_files(root_path, project_path):
    backup_dir = Path('scripts/backup')
    files_to_restore = [
        { "source_name": 'pyproject.toml', "restore_path": root_path / 'pyproject.toml'} ,
        { "source_name": '__version__.py', "restore_path": project_path / '__version__.py'}
    ]
    for file in files_to_restore:
        source_path = Path(backup_dir / file["source_name"])
        if source_path.exists():
            shutil.copy2(source_path, file["restore_path"])
            print(f"Restored {file["source_name"]}")
        else:
            print(f"Backup not found: {file["source_name"]}")


def version_type(version_string):
    if not re.match(r'^\d+\.\d+\.\d+$', version_string):
        raise argparse.ArgumentTypeError("Must be in X.Y.Z format (e.g., 1.2.3)")
    return version_string


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--os",
        metavar="os",
        required=True,
        choices=["windows", "macos", "linux", "ios", "pypi"],
        type=str,
        default="linux",
        help="Choices are: windows, macos, pypi or linux. Default is linux."
    )

    parser.add_argument('--no-appimage', dest='appimage', action='store_false')

    parser.add_argument(
        "--version",
        metavar="version",
        required=True,
        type=version_type,
        help="Version string to use for build."
    )

    args = parser.parse_args()
    os = args.os
    appimage = args.appimage
    package_version = args.version
    output_filename = PACKAGE_NAME
    versionfile_path = None

    logger.info(f"Version determined to be {package_version}")

    logger.info("Backing up files that will be modified by codegen")
    backup_codegen_files(ROOT_PATH, PROJECT_PATH)

    logger.info("Revising files by codegen")
    codegen_version_string(package_version, PROJECT_PATH, ROOT_PATH)

    # Compile translation files
    compile_mo()

    ######### Non-PyInstaller builds #########
    if os == "pypi":
        logger.info("Performing pypi build via poetry")
        result = subprocess.run("poetry build", shell=True, capture_output=True, text=True, check=True)

    if os == "ios":
        # For iOS we need some special handling as it is not supported by pyinstaller
        # Execute the build_ios.sh script
        command = f"{BUILD_PATH}/build_ios.sh {package_version}"
        result = subprocess.run(command, shell=True, capture_output=True, text=True, check=True)
        if result.stderr:
            logger.error(f"Error from build_ios.sh: {result.stderr}")
        logger.info(f"Stdout from build_ios.sh: {result.stdout}")

    ######### Pre PyInstaller tweaks #########
    if os == "windows":
        # Windows needs a versionfile created for metadata in the binary artifact
        versionfile_path = generate_versionfile(
            package_version=package_version,
            output_filename=output_filename,
        )

    ######### Run PyInstaller for all os expcept those that don't use it #########
    if os not in ("ios", "pypi"):
        build_args = build_pyinstaller_args(
            os=os,
            output_filename=output_filename,
            versionfile_path=versionfile_path,
        )
        run_pyinstaller(build_args=build_args)

    ######### Post PyInstaller tweaks #########
    if os == "linux":
        # Need to remove some libs for opinionated backwards compatibility
        # https://github.com/pyinstaller/pyinstaller/issues/6993 
        frozen_dir = f"dist/{PACKAGE_NAME}/_internal"
        remove_shared_libraries(frozen_dir, 'libstdc++.so.*', 'libtinfo.so.*', 'libreadline.so.*', 'libdrm.so.*')

        if appimage:
            run_appimage_builder()
    
    if os == "macos":
        # Need to manually revise the version string due to
        # https://github.com/pyinstaller/pyinstaller/issues/6943
        import PyInstaller.utils.osx as osxutils
        fix_macos_version_string(package_version)
        osxutils.sign_binary(f"dist/{PACKAGE_NAME}.app", deep=True)
    
    logger.info("Restoring files modified by codegen")
    restore_codegen_files(ROOT_PATH, PROJECT_PATH)

if __name__ == "__main__":
    main()
