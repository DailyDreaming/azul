import sys
import argparse

from azul.azulclient import AzulClient
from azul.logging import configure_script_logging


def main(argv):
    parser = argparse.ArgumentParser(description='Delete bundles from Azul index.')
    parser.add_argument('bundles',
                        metavar='UUID.VERSION',
                        type=parse_fqid,
                        nargs='+',
                        help='One or more references of the bundles to be deleted.')
    args = parser.parse_args(argv)
    bundles = args.bundles
    azul_client = AzulClient()
    for bundle in bundles:
        try:
            bundle_uuid, bundle_version = bundle
        except ValueError:
            parser.parse_args(['--help'])
        else:
            azul_client.delete_bundle(bundle_uuid, bundle_version)


def parse_fqid(s: str):
    uuid, _, version = s.partition('.')
    return uuid, version


if __name__ == '__main__':
    configure_script_logging()
    main(sys.argv[1:])
