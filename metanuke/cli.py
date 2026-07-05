"""Meta Nuke CLI — command-line entry point with argparse."""

import argparse
import json
import datetime
import os
import sys
from pathlib import Path

from metanuke import __version__
from metanuke.core import MetaNuke
from metanuke.utils import (
    print_banner,
    collect_files,
    show_preview_collect,
    log_results,
)


def _nuke_one(args_tuple):
    """Process a single file (map helper for multiprocessing)."""
    file_path, noise_level, output_path, backup, strict, rename = args_tuple
    success, message = MetaNuke.nuke_image(
        file_path, noise_level=noise_level,
        output_path=output_path, backup=backup,
        strict=strict, rename=rename,
    )
    return (file_path, success, message)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog='meta_nuke',
        description='Forensically-safe offline metadata stripper',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Examples:\n'
            '  meta_nuke image.jpg\n'
            '  meta_nuke --dir ./photos --recursive --output ./clean\n'
            '  meta_nuke --preview image.jpg\n'
            '  meta_nuke --noise-level 0 image.jpg    # lossless\n'
            '  meta_nuke --ask-noise image.jpg          # prompt before noise\n'
            '  meta_nuke --log nuke.log --dir ./batch\n'
        ),
    )
    parser.add_argument('files', nargs='*', metavar='FILE',
                        help='Image file(s) to nuke')
    parser.add_argument('--dir', '-d', metavar='DIR',
                        help='Process all images in a directory')
    parser.add_argument('--recursive', '-r', action='store_true',
                        help='Recurse into subdirectories (with --dir)')
    parser.add_argument('--output', '-o', metavar='DIR',
                        help='Output directory (default: overwrite in-place)')
    parser.add_argument('--backup', '-b', action='store_true',
                        help='Keep a .bak copy of each original (in-place mode only)')
    parser.add_argument('--noise-level', '-n', type=int, default=5,
                        choices=range(0, 11),
                        help='Forensic noise level 0-10 (0=off, 5=default, 10=max)')
    parser.add_argument('--ask-noise', action='store_true',
                        help='Prompt before applying forensic noise (y/N)')
    parser.add_argument('--strict', action='store_true',
                        help='Fail on any silently-swallowed operation (ICC, PDF image)')
    parser.add_argument('--jobs', '-j', type=int, default=1,
                        help='Number of parallel worker processes (default: 1, single-threaded)')
    parser.add_argument('--rename', action='store_true',
                        help='Rename output to SHA256 content-hash (prevents filename leakage; requires --output)')
    parser.add_argument('--preview', '-p', action='store_true',
                        help='Preview metadata before nuking (no changes)')
    parser.add_argument('--log', '-l', metavar='FILE',
                        help='Append audit log to FILE')
    parser.add_argument('--no-banner', action='store_true',
                        help='Suppress the ASCII banner')
    parser.add_argument('--gui', action='store_true',
                        help='Force GUI mode (with optional file arguments)')
    parser.add_argument('--json', action='store_true',
                        help='Output results as JSON (machine-readable)')
    parser.add_argument('--version', action='store_true',
                        help='Show version and exit')

    args = parser.parse_args()

    if args.version:
        print(f"Meta Nuke v{__version__}")
        return

    if args.gui:
        from metanuke.gui import MetaNukeGUI
        app = MetaNukeGUI(preloaded_files=args.files or None)
        app.run()
        return

    if not args.files and not args.dir:
        from metanuke.gui import MetaNukeGUI
        app = MetaNukeGUI()
        app.run()
        return

    sources = list(args.files)
    if args.dir:
        sources.append(args.dir)

    if not sources:
        parser.print_help()
        return

    all_files = collect_files(sources, recursive=args.recursive)

    if not all_files:
        print("No supported image files found.")
        return

    if args.preview:
        if not args.no_banner:
            print_banner()
        print(f"Scanning {len(all_files)} file(s) for metadata...\n")
        show_preview_collect(all_files)
        return

    if not args.no_banner:
        print_banner()

    use_tqdm = False
    if not args.json:
        try:
            from tqdm import tqdm
            progress = tqdm(total=len(all_files), unit='file',
                            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}]')
            use_tqdm = True
        except ImportError:
            progress = None

    results = []
    use_mp = args.jobs > 1 and not args.ask_noise

    if use_mp:
        import multiprocessing as _mp
        if use_tqdm:
            progress.close()
            use_tqdm = False
        pool_args = []
        for file_path in all_files:
            output_path = None
            if args.output:
                src = Path(file_path)
                out_dir = Path(args.output)
                out_dir.mkdir(parents=True, exist_ok=True)
                output_path = str(out_dir / src.name)
            pool_args.append((
                file_path, args.noise_level, output_path,
                args.backup, args.strict, args.rename,
            ))
        with _mp.Pool(args.jobs) as pool:
            raw_results = pool.map(_nuke_one, pool_args)
        results = list(raw_results)
        if not args.json:
            for f, s, m in results:
                status = "✓" if s else "✗"
                print(f"  {status}  {m}")
    else:
        for i, file_path in enumerate(all_files):
            if not use_tqdm and not args.json:
                print(f"  [{i+1}/{len(all_files)}] {Path(file_path).name} ...",
                      end=" ", flush=True)

            output_path = None
            if args.output:
                src = Path(file_path)
                out_dir = Path(args.output)
                out_dir.mkdir(parents=True, exist_ok=True)
                output_path = str(out_dir / src.name)

            effective_noise = args.noise_level
            if args.ask_noise and effective_noise > 0:
                try:
                    resp = input(f"  Apply forensic noise (level {effective_noise}) to {Path(file_path).name}? (y/N): ")
                    if resp.strip().lower() not in ('y', 'yes'):
                        effective_noise = 0
                except (EOFError, KeyboardInterrupt):
                    effective_noise = 0

            success, message = MetaNuke.nuke_image(
                file_path, noise_level=effective_noise, output_path=output_path,
                backup=args.backup, strict=args.strict, rename=args.rename,
            )

            if use_tqdm:
                status = "✓" if success else "✗"
                progress.set_postfix_str(f"{status} {Path(file_path).name}")
                progress.update(1)
            elif not args.json:
                status = "✓" if success else "✗"
                print(f"{status}  {message}")

            results.append((file_path, success, message))

    if use_tqdm:
        progress.close()
        print()

    total = len(results)
    ok = sum(1 for _, s, _ in results if s)
    bad = total - ok

    if args.json:
        output = {
            'tool': 'meta-nuke',
            'version': __version__,
            'timestamp': datetime.datetime.now().isoformat(),
            'total': total,
            'success': ok,
            'failed': bad,
            'results': [
                {'file': p, 'success': s, 'message': m}
                for p, s, m in results
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"  {ok}/{total} nuked  ·  {bad} failed")

    if args.log:
        log_results(args.log, results)
        print(f"  Log: {args.log}")


if __name__ == "__main__":
    main()
