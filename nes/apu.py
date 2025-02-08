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
		pass  # TODO
