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
    parser.add_argument('--noise-level', '-n', type=int, default=5,
                        choices=range(0, 11),
                        help='Forensic noise level 0-10 (0=off, 5=default, 10=max)')
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

        success, message = MetaNuke.nuke_image(
            file_path, noise_level=args.noise_level, output_path=output_path,
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
