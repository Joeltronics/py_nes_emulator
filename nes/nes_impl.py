#!/usr/bin/env python3

from nes.apu import Apu
from nes.controllers import Controllers
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
			breakpoints: bool = False,
			sleep_cpu: bool = True,
			log_instructions_to_file: bool = False,
			log_instructions_to_stream: bool = False,
			render: bool = True,
			):

		if rom.header.mapper != 0:
			raise NotImplementedError(f'Only mapper 0 is implemented (ROM has mapper {rom.header.mapper})')

		self.rom = rom

		self.controllers = Controllers()

		self.ui = None
		self.renderer = None
		if render:
			self.renderer = Renderer(
				rom_chr=self.rom.chr,
				rom_header=self.rom.header,
			)
			self.ui = Ui(
				controllers=self.controllers,
				renderer=self.renderer,
			)

		self.apu = Apu()
		self.ppu = Ppu(
			rom_chr=self.rom.chr,
			rom_header=self.rom.header,
		)
		self.cpu = Cpu(
			rom_prg=self.rom.prg,
			apu=self.apu,
			ppu=self.ppu,
			controllers=self.controllers,
			sleep_on_branch_loop=sleep_cpu,
			log_instructions_to_file=log_instructions_to_file,
			log_instructions_to_stream=log_instructions_to_stream,
			stop_on_brk=breakpoints,
			stop_on_rti=breakpoints,
			stop_on_vblank_start=breakpoints,
			stop_on_vblank_end=breakpoints,
		)

	def _handle_breakpoint(self):

		print('Breakpoint')

		while True:
			if self.ui:
				self.ui.handle_events()
			val = input('Enter to step, or "c" to continue: ').strip().lower()

			if not val:
				# Step
				self.cpu.process_instruction()
				continue
			elif val.startswith('c'):
				return

	def run(self):

		# TODO: log FPS (and how much time was emulation vs rendering vs UI)

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
				if self.cpu.process_instruction():
					self._handle_breakpoint()

	def run_until_next_vblank_start(self):

		while self.ppu.vblank:
			if self.cpu.process_instruction():
				self._handle_breakpoint()

		while not self.ppu.vblank:
			if self.cpu.process_instruction():
				self._handle_breakpoint()
