#!/usr/bin/env python3

from typing import Final

from nes.types import pointer16, uint8


class Apu:
	def __init__(self):
		self._registers: Final[bytearray] = bytearray(0x20)

	@property
	def registers(self):
		return self._registers

	def read_reg_from_cpu(self, addr: pointer16) -> uint8:
		"""
		Read register in the range 0x4000-0x401F
		"""
		if addr == 0x4015:
			raise NotImplementedError(f'Reading audio status $4015 not yet supported')
		else:
			raise Exception(f'Cannot read from register ${addr:04X}')

	def write_reg_from_cpu(self, addr: pointer16, value: uint8) -> None:
		"""
		Write register in the range 0x4000-0x401F
		"""

		if addr == 0x4017:
			irq_inhibit = bool(value & 0b0100_0000)
			if not irq_inhibit:
				raise NotImplementedError('APU IRQ is not yet supported')

		try:
			self._registers[addr - 0x4000] = value
		except IndexError as ex:
			raise Exception(f'Invalid address: ${addr:04X}') from ex
