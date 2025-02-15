#!/usr/bin/env python3

class Apu:
	def __init__(self):
		pass

	def read_reg_from_cpu(self, reg: int) -> int:
		"""
		Read register in the range 0x4000-0x401F
		"""
		return 0  # TODO

	def write_reg_from_cpu(self, addr: int, val: int) -> None:
		"""
		Write register in the range 0x4000-0x401F
		"""

		if addr == 0x4017:
			irq_inhibit = bool(val & 0b0100_0000)
			if not irq_inhibit:
				raise NotImplementedError('APU IRQ is not yet supported')

		pass  # TODO
