#!/usr/bin/env python3

from nes.types import uint8, pointer16

class Ppu:
	def __init__(self, rom_chr: bytes):
		self.rom_chr = rom_chr

	def tick_clock_fom_cpu(self, cpu_cycles: int) -> None:
		pass  # TODO

	def read_reg_from_cpu(self, reg: pointer16) -> uint8:
		"""
		Read register in the range 0x2000-0x2007
		"""
		return 0  # TODO

	def write_reg_from_cpu(self, addr: pointer16, val: uint8) -> None:
		"""
		Write register in the range 0x2000-0x2007
		"""
		pass  # TODO

	def wait_for_ppustatus_change(self) -> None:
		raise NotImplementedError('TODO: wait_for_ppustatus_change()')

	def oam_dma(self, data: bytes) -> None:
		"""
		Start an OAM DMA
		"""
		pass  # TODO
