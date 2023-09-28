import ast
import os
import pkg_resources
import re
from collections import defaultdict

from vdb.lib import db as db_lib
from vdb.lib.utils import version_compare

from depscan.lib import config, normalize

lic_symbol_regex = re.compile(r"[(),]")


def filter_ignored_dirs(dirs):
    """
    Method to filter directory list to remove ignored directories

    :param dirs: Directories to ignore
    :return: Filtered directory list
    """
    [
        dirs.remove(d)
        for d in list(dirs)
        if d.lower() in config.ignore_directories or d.startswith(".")
    ]
    return dirs

def find_files(src, src_ext_name, quick=False, filter=True):
    """
    Method to find files with given extension

    :param src: source directory to search
    :param src_ext_name: type of source file
    :param quick: only return first match found
    :param filter: filter out ignored directories
    """
    result = []
    for root, dirs, files in os.walk(src):
        if filter:
            filter_ignored_dirs(dirs)
        for file in files:
            if file == src_ext_name or file.endswith(src_ext_name):
                result.append(os.path.join(root, file))
                if quick:
                    return result
    return result


def is_binary_string(content):
    """
    Method to check if the given content is a binary string
    """
    textchars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7F})
    return bool(content.translate(None, textchars))


def is_exe(src):
    """
    Detect if the source is a binary file

    :param src: Source path
    :return True if binary file. False otherwise.
    """
    if os.path.isfile(src):
        try:
            return is_binary_string(open(src, "rb").read(1024))
        except Exception:
            return False
    return False


def detect_project_type_from_file(file_name):
    """
    Detect project type from file name
    
    :param file_name: File name
    :return: Project type(s)
    """
    project_types = []

    for project_type in config.PROJECT_TYPES:
        file_extensions = config.PROJECT_TYPES[project_type]
        for file_extension in file_extensions:
            if file_extension in file_name:
                project_types.append(project_type)
                break
    if is_exe(file_name):
        project_types.extend(['binary', 'go'])
    if os.path.join(".github", "workflows") in file_name:
        project_types.append('github')
    return project_types

def detect_project_type(src_dir):
    """Detect project type by looking for certain files

    :param src_dir: Source directory
    :return List of detected project types
    """
    if os.path.isfile(src_dir):
        return detect_project_type_from_file(src_dir)
    
    project_types = []
    for root, dirs, files in os.walk(src_dir):
        filter_ignored_dirs(dirs)
        for file in files:
            project_types.extend(detect_project_type_from_file(os.path.abspath(os.path.join(root, file))))
    return list(set(project_types))


def get_pkg_vendor_name(pkg):
    """
    Method to extract vendor and name information from package. If vendor
    information is not available package url is used to extract the package
    registry provider such as pypi, maven

    :param pkg: a dictionary representing a package
    :return: vendor and name as a tuple
    """
    vendor = pkg.get("vendor")
    if not vendor:
        purl = pkg.get("purl")
        if purl:
            purl_parts = purl.split("/")
            if purl_parts:
                vendor = purl_parts[0].replace("pkg:", "")
        else:
            vendor = ""
    name = pkg.get("name")
    return vendor, name


def search_pkgs(db, project_type, pkg_list):
    """
    Method to search packages in our vulnerability database

    :param db: DB instance
    :param project_type: Project type
    :param pkg_list: List of packages to search
    :returns: raw_results, pkg_aliases, purl_aliases
    """
    expanded_list = []
    # The challenge we have is to broaden our search and create several
    # variations of the package and vendor names to perform a broad search.
    # We then have to map the results back to the original package names and
    # package urls.
    pkg_aliases = defaultdict(list)
    purl_aliases = {}
    for pkg in pkg_list:
        variations = normalize.create_pkg_variations(pkg)
        if variations:
            expanded_list += variations
        vendor, name = get_pkg_vendor_name(pkg)
        version = pkg.get("version")
        if pkg.get("purl"):
            purl_aliases[pkg.get("purl")] = pkg.get("purl")
            purl_aliases[f"{vendor.lower()}:{name.lower()}:{version}"] = pkg.get("purl")
            if not purl_aliases.get(f"{vendor.lower()}:{name.lower()}"):
                purl_aliases[f"{vendor.lower()}:{name.lower()}"] = pkg.get("purl")
        if variations:
            for vari in variations:
                vari_full_pkg = f"""{vari.get("vendor")}:{vari.get("name")}"""
                pkg_aliases[f"{vendor.lower()}:{name.lower()}:{version}"].append(
                    vari_full_pkg
                )
                purl_aliases[f"{vari_full_pkg.lower()}:{version}"] = pkg.get("purl")
    quick_res = db_lib.bulk_index_search(expanded_list)
    raw_results = db_lib.pkg_bulk_search(db, quick_res)
    raw_results = normalize.dedup(project_type, raw_results)
    pkg_aliases = normalize.dealias_packages(
        raw_results,
        pkg_aliases=pkg_aliases,
        purl_aliases=purl_aliases,
    )
    return raw_results, pkg_aliases, purl_aliases


def get_pkgs_by_scope(pkg_list):
    """
    Method to return the packages by scope as defined in CycloneDX spec -
    required, optional and excluded

    :param pkg_list: List of packages
    :return: Dictionary of packages categorized by scope if available. Empty if
                no scope information is available
    """
    scoped_pkgs = {}
    for pkg in pkg_list:
        if pkg.get("scope"):
            vendor, name = get_pkg_vendor_name(pkg)
            scope = pkg.get("scope").lower()
            if pkg.get("purl"):
                scoped_pkgs.setdefault(scope, []).append(pkg.get("purl"))
            else:
                scoped_pkgs.setdefault(scope, []).append(f"{vendor}:{name}")
    return scoped_pkgs


def get_scope_from_imports(project_type, pkg_list, all_imports):
    """
    Method to compute the packages scope defined in CycloneDX spec - required,
    optional and excluded

    :param project_type: Project type
    :param pkg_list: List of packages
    :param all_imports: List of imports detected
    :return: Dictionary of packages categorized by scope if available. Empty if
                no scope information is available
    """
    scoped_pkgs = {}
    if not pkg_list or not all_imports:
        return scoped_pkgs
    for pkg in pkg_list:
        scope = "optional"
        vendor, name = get_pkg_vendor_name(pkg)
        if name in all_imports or name.lower().replace("py", "") in all_imports:
            scope = "required"
        if pkg.get("purl"):
            scoped_pkgs.setdefault(scope, []).append(pkg.get("purl"))
        else:
            scoped_pkgs.setdefault(scope, []).append(f"{vendor}:{name}")
        scoped_pkgs[scope].append(f"{project_type}:{name.lower()}")
    return scoped_pkgs


def cleanup_license_string(license_str):
    """
    Method to clean up license string by removing problematic symbols and
    making certain keywords consistent

    :param license_str: String to clean up
    :return: Cleaned up version
    """
    if not license_str:
        license_str = ""
    license_str = (
        license_str.replace(" / ", " OR ")
        .replace("/", " OR ")
        .replace(" & ", " OR ")
        .replace("&", " OR ")
    )
    license_str = lic_symbol_regex.sub("", license_str)
    return license_str.upper()


def max_version(version_list):
    """
    Method to return the highest version from the list

    :param version_list: single version string or set of versions
    :return: max version
    """
    if isinstance(version_list, str):
        return version_list
    if isinstance(version_list, set):
        version_list = list(version_list)
    if len(version_list) == 1:
        return version_list[0]
    min_ver = "0"
    max_ver = version_list[0]
    for i, vl in enumerate(version_list):
        if not vl:
            continue
        if not version_compare(vl, min_ver, max_ver):
            max_ver = vl
    return max_ver


def get_all_imports(src_dir):
    """
    Method to collect all package imports from a python file
    No longer required since cdxgen does python analysis already
    """
    import_list = set()
    py_files = find_files(src_dir, ".py")
    if not py_files:
        return import_list
    for afile in py_files:
        with open(os.path.join(afile), "rb", encoding="utf-8") as f:
            content = f.read()
        parsed = ast.parse(content)
        for node in ast.walk(parsed):
            if isinstance(node, ast.Import):
                for name in node.names:
                    pkg = name.name.split(".")[0]
                    import_list.add(pkg)
                    import_list.add(pkg.lower().replace("py", ""))
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    continue
                if getattr(node, "module"):
                    if node.module:
                        pkg = node.module.split(".")[0]
                        import_list.add(pkg)
                        import_list.add(pkg.lower().replace("py", ""))
    return import_list


def get_version():
    """
    Returns the version of depscan
    """
    return pkg_resources.get_distribution("owasp-depscan").version
