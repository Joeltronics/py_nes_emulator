#!/usr/bin/env python3

from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
import logging
from pathlib import Path

# from colorama import Fore, Style

from nes import Nes, Rom
from utils import logging_utils


def parse_args():
	p = ArgumentParser()
	p.add_argument('rom_path', type=Path)
	p.add_argument('--headless', action='store_true')
	p.add_argument('--stop', metavar='FRAMES', dest='stop_after_frames', type=int, default=0, help='Stop after this many frames')

	p.set_defaults(verbosity=0)
	mx = p.add_mutually_exclusive_group()
	mx.add_argument('-v', action='store_const', dest='verbosity', const=1, help='Verbose')
	mx.add_argument('--vv', action='store_const', dest='verbosity', const=2, help='Extra verbose')
	mx.add_argument('--vvv', action='store_const', dest='verbosity', const=3, help='Extra verbose')

	args = p.parse_args()

	return args


def main():
	args = parse_args()

	logging_utils.init_logging(
		stream_level=logging.DEBUG if (args.verbosity >= 2) else logging.INFO,
	)

	rom = Rom(args.rom_path)

	print(f'{rom.header=}')

	nes = Nes(
		rom,
		log_instructions_to_file=True,
		log_instructions_to_stream=(args.verbosity >= 3),
		render=(not args.headless),
	)

	if args.stop_after_frames:
		print(f'Emulating for {args.stop_after_frames} frames...')
		for _ in range(args.stop_after_frames + 1):
			nes.run_until_next_vblank_start()
	else:
		print('Emulating...')
		nes.run()


if __name__ == "__main__":
	main()
