# coding: utf-8

# Following site is used for reference
# https://hitkey.nekokan.dyndns.info/cmds.htm

# Abandon all hope ye who enter here


import sys
from argparse import ArgumentParser
from os import devnull, makedirs, path

from tqdm import tqdm

import bm2sm.BM_parser

tqdm.monitor_interval = 0


def convert(in_file, out_dir, keys, mode, seed=None):
    parser = bm2sm.BM_parser.BMChartParser(in_file, out_dir, keys, mode != 'SM', seed)

    if mode != 'AUDIO':
        parser.SM_converter.compose_chart()

    if mode != 'SM':
        parser.OGG_converter.bake_audio()

    parser.copy_files()


def read_file_list(list_file):
    """One chart path per line. Empty lines and lines starting with # are skipped, surrounding quotes are removed."""
    with open(list_file, 'r', encoding='utf-8-sig') as f:
        lines = (line.strip() for line in f)
        return [line.strip('"\'') for line in lines if line and not line.startswith('#')]


def batch_convert(in_files, out_dir, keys, mode, seed=None):
    # Status goes to the real stdout, since non-verbose mode silences sys.stdout
    status = sys.__stdout__
    used_names = set()
    failed = []

    # A chart counts as a duplicate if its file name and the name of its folder match an earlier one,
    #   so the same song copied to several places is converted once
    unique_files = []
    seen_charts = set()
    for in_file in in_files:
        real_path = path.realpath(in_file)
        chart_key = (path.basename(path.dirname(real_path)).casefold(), path.basename(real_path).casefold())
        if chart_key in seen_charts:
            print('Skipping duplicate: {}'.format(in_file), file=status)
            continue
        seen_charts.add(chart_key)
        unique_files.append(in_file)
    in_files = unique_files

    for number, in_file in enumerate(in_files, 1):
        # Each chart gets its own subfolder named after it, charts with the same name get a numbered suffix
        base_name = path.splitext(path.basename(in_file))[0]
        name = base_name
        suffix = 2
        while name.lower() in used_names:
            name = '{} ({})'.format(base_name, suffix)
            suffix += 1
        used_names.add(name.lower())

        chart_out_dir = path.join(out_dir, name)
        print('[{}/{}] {}'.format(number, len(in_files), in_file), file=status, flush=True)
        try:
            if not path.isfile(in_file):
                raise FileNotFoundError('File not found')
            makedirs(chart_out_dir, exist_ok=True)
            convert(in_file, chart_out_dir, keys, mode, seed)
        except Exception as e:
            failed.append(in_file)
            print('    Failed: {}: {}'.format(type(e).__name__, e), file=status, flush=True)

    print('Converted {} of {} charts.'.format(len(in_files) - len(failed), len(in_files)), file=status)
    if failed:
        print('Failed:', file=status)
        for in_file in failed:
            print('    ' + in_file, file=status)
    return not failed


if __name__ == '__main__':
    arg_parser = ArgumentParser(description='Convert BM files to SM',
                                add_help=True,
                                allow_abbrev=True)

    input_group = arg_parser.add_mutually_exclusive_group(required=True)

    input_group.add_argument('-I', '--in_file',
                             action='store',
                             help='Path to file to be converted.',
                             type=str)

    input_group.add_argument('-L', '--list',
                             action='store',
                             help='Batch conversion: path to a text file with one chart path per line. '
                                  'Each chart is written into its own subfolder of --out_dir, '
                                  'named after the chart file. Empty lines and lines starting with # are skipped.',
                             type=str)

    arg_parser.add_argument('-O', '--out_dir',
                            action='store',
                            default=None,
                            help='Where to write converted files. Default: Same directory as specified in --in_file. '
                                 'Required with --list.',
                            type=str)

    arg_parser.add_argument('-K', '--keys',
                            action='store',
                            default=None,
                            help="How the keys from BM chart map onto SM chart. Accepted string lengths: 4, 5, 6, 7, "
                                 "8, 10 characters. 1-7 means KEY1-KEY7, S means scratch track, X means empty "
                                 "track. Only leftmost value is used, so duplicated values are treated the same as X. "
                                 "Default: the bm-single7 game mode (7 keys and scratch).",
                            type=str)

    arg_parser.add_argument('-M', '--mode',
                            action='store',
                            choices=['ALL', 'SM', 'AUDIO'],
                            default='ALL',
                            help='Converter mode, useful for batch conversion. '
                                 'SM will only convert to SM chart. AUDIO only bakes OGG audio file. '
                                 'ALL does both. '
                                 'Default: ALL.')

    arg_parser.add_argument('-S', '--seed',
                            action='store',
                            default=None,
                            help='Seed for charts using #RANDOM/#SWITCH, which get random branches picked. '
                                 'The same seed always picks the same branches. Default: a new random pick every time.',
                            type=int)

    arg_parser.add_argument('-V', '--verbose',
                            action='store_true',
                            default=False,
                            help='Verbose mode, will print all kinds of messages if set.')

    args = arg_parser.parse_args()

    if args.list and not args.out_dir:
        arg_parser.error('--out_dir is required with --list')

    if args.out_dir and not path.exists(args.out_dir):
        makedirs(args.out_dir)

    if not args.verbose:
        sys.stdout = open(devnull, 'w')  # Null file
        sys.stderr = sys.stdout  # Another one for progress bars

    if args.list:
        success = batch_convert(read_file_list(args.list), args.out_dir, args.keys, args.mode, args.seed)
        sys.exit(0 if success else 1)

    if not args.out_dir:
        args.out_dir = path.split(args.in_file)[0]

    try:
        convert(args.in_file, args.out_dir, args.keys, args.mode, args.seed)
    except Exception as e:
        if args.verbose:
            raise
        # Non-verbose mode silences stderr, so the error would otherwise be lost
        print('Failed: {}: {}'.format(type(e).__name__, e), file=sys.__stderr__)
        sys.exit(1)
