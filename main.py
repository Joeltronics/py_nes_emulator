#!/usr/bin/env python3

import logging
logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)

from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from pathlib import Path

# from colorama import Fore, Style

from nes import Nes, Rom


def parse_args():
	p = ArgumentParser()
	p.add_argument('rom_path', type=Path)
	args = p.parse_args()
	return args


def main():
	args = parse_args()

	rom = Rom(args.rom_path)

	print(f'{rom.header=}')

	nes = Nes(rom)

	nes.cpu.instruction_logger = logging.getLogger('cpu')
	nes.cpu.instruction_logger.setLevel(logging.DEBUG)

	print('Emulating...')
	while True:
		# instr = nes.cpu.rom_prg[nes.cpu.pc % len(nes.cpu.rom_prg)]
		# print(f'pc=0x{nes.cpu.pc:04X}, instr=0x{instr:02X}')
		nes.cpu.process_instruction()


if __name__ == "__main__":
	main()
