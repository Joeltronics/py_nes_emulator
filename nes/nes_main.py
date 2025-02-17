#!/usr/bin/env python3

import time

from nes.apu import Apu
from nes.controllers import Controllers
from nes.cpu import Cpu
from nes.ppu import Ppu
from nes.renderer import Renderer
from nes.rom import Rom
from nes.ui import Ui


class PerformanceTimer:
	def __init__(self):
		self._frame_start = None
		self._last_checkin = None
		self._sums = dict()
		self._num_frames = 0
		self._last_dump = time.perf_counter()
		self._fps_str = ''

	def fps_str(self) -> str:
		return self._fps_str

	def start_frame(self) -> None:
		now = time.perf_counter()
		self._last_checkin = self._frame_start = now
		if self._last_dump is None:
			self._last_dump = now

	def checkin(self, name: str) -> None:

		now = time.perf_counter()
		delta = now - self._last_checkin
		self._last_checkin = now

		assert delta >= 0

		if name not in self._sums:
			self._sums[name] = 0.0
		self._sums[name] += delta

	def end_frame(self) -> None:
		now = time.perf_counter()

		frame_time = now - self._frame_start  # TODO: use this

		self._num_frames += 1

		delta = now - self._last_dump
		if delta >= 1.0:
			self._dump(now)

	def _dump(self, now) -> None:

		elapsed = now - self._last_dump

		assert elapsed > 0
		assert self._num_frames > 0

		fps = self._num_frames / elapsed

		# TODO: print section averages

		self._fps_str = f'{fps:.1f} FPS'

		total = sum(self._sums.values())
		for k, v in self._sums.items():
			# self._fps_str += f'\n{k}:{v/total:.1%}'
			t = v / self._num_frames * 1000
			self._fps_str += f'\n{k}: {t:.1f} ms'

		# print(self._fps_str)

		self._last_dump = now
		self._sums = dict()
		self._num_frames = 0


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
			timer = PerformanceTimer()

			self.ui.draw()

			while self.ui.running:

				timer.start_frame()

				self.run_until_next_vblank_start()
				timer.checkin('Emu')

				# TODO: don't only render at vblank, to allow for mid-frame PPU changes
				self.renderer.render_frame(self.ppu)
				timer.checkin('Render')

				fps_str = timer.fps_str()

				self.ui.draw(fps_str)
				timer.checkin('Draw')

				self.ui.flip()
				timer.checkin('Flip')

				self.ui.handle_events()
				timer.checkin('Events')

				timer.end_frame()

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
