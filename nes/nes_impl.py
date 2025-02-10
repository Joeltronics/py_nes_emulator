#!/usr/bin/env python3

from nes.apu import Apu
from nes.cpu import Cpu
from nes.ppu import Ppu
from nes.rom import Rom

class Nes:
	def __init__(
			self,
			rom: Rom,
			*,
			stop_after_frames: int = 0,
			log_instructions_to_file: bool = False,
			log_instructions_to_stream: bool = False,
			):

		if rom.header.mapper != 0:
			raise NotImplementedError(f'Only mapper 0 is implemented (ROM has mapper {rom.header.mapper})')

		self.rom = rom
		self.apu = Apu()
		self.ppu = Ppu(rom_chr=self.rom.chr, rom_header=self.rom.header, stop_after_frames=stop_after_frames)
		self.cpu = Cpu(
			rom_prg=self.rom.prg,
			apu=self.apu,
			ppu=self.ppu,
			log_instructions_to_file=log_instructions_to_file,
			log_instructions_to_stream=log_instructions_to_stream,
		)
