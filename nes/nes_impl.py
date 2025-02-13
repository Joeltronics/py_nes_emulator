#!/usr/bin/env python3

from nes.apu import Apu
from nes.cpu import Cpu
from nes.ppu import Ppu
from nes.renderer import Renderer
from nes.rom import Rom
from nes.ui import Ui


class Nes:
	def __init__(
			self,
			rom: Rom,
			*,
			log_instructions_to_file: bool = False,
			log_instructions_to_stream: bool = False,
			render: bool = True,
			):

		if rom.header.mapper != 0:
			raise NotImplementedError(f'Only mapper 0 is implemented (ROM has mapper {rom.header.mapper})')

		self.rom = rom

		self.ui = None
		self.renderer = None
		if render:
			self.renderer = Renderer(
				rom_chr=self.rom.chr,
				rom_header=self.rom.header,
			)
			self.ui = Ui(renderer=self.renderer)

		self.apu = Apu()
		self.ppu = Ppu(
			rom_chr=self.rom.chr,
			rom_header=self.rom.header,
		)
		self.cpu = Cpu(
			rom_prg=self.rom.prg,
			apu=self.apu,
			ppu=self.ppu,
			log_instructions_to_file=log_instructions_to_file,
			log_instructions_to_stream=log_instructions_to_stream,
		)

	def run(self):

		if self.ui:
			assert self.renderer

			self.ui.draw()

			while self.ui.running:
				self.run_until_next_vblank_start()
				# TODO: don't only render at vblank, to allow for mid-frame PPU changes
				self.renderer.render_frame(self.ppu)
				self.ui.draw()
				self.ui.handle_events()

		else:

			while True:
				self.cpu.process_instruction()


	def run_until_next_vblank_start(self):

		while self.ppu.vblank:
			self.cpu.process_instruction()

		while not self.ppu.vblank:
			self.cpu.process_instruction()
