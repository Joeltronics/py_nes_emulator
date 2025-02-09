#!/usr/bin/env python3

import logging
from typing import Final

from nes.apu import Apu
from nes.ppu import Ppu
from nes.types import uint8, int8, pointer16


def _signed(val: uint8) -> int8:
	"""
	Convert unsigned 8-bit to signed 8-bit
	"""
	assert 0 <= val < 256
	return val if (val < 128) else (val - 256)


def _unsigned(val: int8) -> uint8:
	"""
	Convert signed 8-bit to unsigned 8-bit
	"""
	assert -128 <= val <= 127
	return val if (val >= 0) else (val + 256)


for uval in [0, 1, 126, 127, 128, 129, 254, 255]:
	assert _unsigned(_signed(uval)) == uval


for sval in [0, 1, 2, -1, -2, 126, 127, -128, -127]:
	assert _signed(_unsigned(sval)) == sval



class Cpu:
	def __init__(
			self, *,
			rom_prg: bytes, ppu: Ppu, apu: Apu, stop_on_brk: bool = False, log_instructions: bool = False):

		self.rom_prg: Final[bytes] = rom_prg
		self.ppu: Final[Ppu] = ppu
		self.apu: Final[Apu] = apu
		self.stop_on_brk: bool = stop_on_brk

		self.ram: Final[bytearray] = bytearray(2048)

		logging.debug(f'len(rom_prg)=0x{len(rom_prg):04X}')

		self.nmi: Final[pointer16] = self.read16(0xFFFA)
		self.reset: Final[pointer16] = self.read16(0xFFFC)
		self.irq: Final[pointer16] = self.read16(0xFFFE)

		logging.debug(f'NMI: 0x{self.nmi:04X}')
		logging.debug(f'RESET: 0x{self.reset:04X}')
		logging.debug(f'IRQ: 0x{self.irq:04X}')

		# CPU state
		self.sp: uint8 = 0xFD
		self.pc: pointer16 = self.reset
		self.a: uint8 = 0
		self.x: uint8 = 0
		self.y: uint8 = 0

		self.n: bool = False
		self.v: bool = False
		self.b: bool = False
		self.d: bool = False
		self.i: bool = True
		self.z: bool = False
		self.c: bool = False

		self.vblank_needs_handling: bool = False

		# TODO: use a weakref (this leads to circular reference, not sure if Python gc can handle it properly)
		ppu.vblank_start_callback = self.vblank_start_callback

		# Detect repeated reads to $2002
		# TODO: smarter, more general purpose "PPU read loop" detector
		self.read_ppustatus_counter: uint8 = 0
		self.last_ppustatus: uint8 = 0

		self.instruction_logger = None
		if log_instructions:
			self.instruction_logger = logging.getLogger('instructions')

		# These are just for debugging
		self.clock: int = 0
		self.vblank_count: int = 0

	# Status register

	@property
	def sr(self) -> uint8:
		return (
			int(self.n) << 7 |
			int(self.v) << 6 |
			int(self.b) << 4 |
			int(self.d) << 3 |
			int(self.i) << 2 |
			int(self.z) << 1 |
			int(self.c)
		)

	@sr.setter
	def sr(self, sr: uint8) -> None:
		self.n = bool(sr & 0b1000_0000)
		self.v = bool(sr & 0b0100_0000)
		self.b = bool(sr & 0b0001_0000)
		self.d = bool(sr & 0b0000_1000)
		self.i = bool(sr & 0b0000_0100)
		self.z = bool(sr & 0b0000_0010)
		self.c = bool(sr & 0b0000_0001)

	@property
	def sr_str(self) -> str:
		return (
			('N' if self.n else '-') +
			('V' if self.v else '-') +
			'-' +
			('B' if self.b else '-') +
			('D' if self.d else '-') +
			('I' if self.i else '-') +
			('Z' if self.z else '-') +
			('C' if self.c else '-')
		)

	# Read & write memory

	def read(self, addr: pointer16) -> uint8:

		assert 0 <= addr < 65536, f'Invalid address: {addr}'

		if addr < 0x2000:
			# RAM
			return self.ram[addr & 0x07FF]

		elif addr < 0x4000:
			# PPU
			wrapped_addr = 0x2000 + (addr & 0x07)
			value = self.ppu.read_reg_from_cpu(wrapped_addr)
			if wrapped_addr == 0x2002:
				# TODO: move PPUSTATUS detector into its own class
				if value == self.last_ppustatus:
					self.read_ppustatus_counter += 8
					if self.read_ppustatus_counter >= 16:
						if self.instruction_logger:
							self.instruction_logger.info('Detected repeated PPUSTATUS reads, waiting for it to change')
						self.ppu.wait_for_ppustatus_change()
				else:
					self.read_ppustatus_counter = 0
					self.last_ppustatus = value
			return value

		elif addr < 0x4020:
			# APU
			return self.apu.read_reg_from_cpu(addr)

		elif addr < 0x8000:
			# TODO: Support mappers, or otherwise emulate behavior if no mapper (open-bus?)
			return 0

		else:
			# return self.rom_prg[(addr - 0x8000)]
			# return self.rom_prg[(addr - 0x8000) % len(self.rom_prg)]
			return self.rom_prg[addr % len(self.rom_prg)]

	def read16(self, addr: pointer16) -> uint8:
		# TODO optimization
		low = self.read(addr)
		high = self.read(addr + 1)
		return (high << 8) + low

	def write(self, addr: pointer16, val: uint8) -> None:

		assert 0 <= addr < 65536, f'Invalid address: {addr}'

		if addr == 0x4014:
			# OAMDMA
			self.oam_dma(val)

		elif addr < 0x2000:
			# RAM
			self.ram[addr & 0x07FF] = val

		elif addr < 0x4000:
			# PPU
			self.ppu.write_reg_from_cpu(0x2000 + (addr & 0x07), val)

		elif addr < 0x4020:
			# APU
			self.apu.write_reg_from_cpu(addr, val)

		# TODO: support mappers

	# def write16(self, addr: pointer16, value: uint8) -> None:
	# 	# TODO: optimize this
	# 	self.write(addr, value & 0xFF)
	# 	self.write(addr + 1, (value & 0xFF00) >> 8)

	# DMA

	def oam_dma(self, page: uint8) -> None:
		if self.instruction_logger:
			self.instruction_logger.debug(f'OAMDMA ${page:02X}00-${page:02X}FF')

		# TODO: For more accurate emulation, copy 1 byte at a time

		if page < 0x20:
			start = (page * 256) & 0x7FF
			end = start + 256
			self.ppu.oam_dma(self.ram[start:end])
		else:
			raise NotImplementedError('OAM DMA from memory outside RAM is not currently supported')

		self._tick_clock(513)  # TODO: sometimes 514 cycles

	# Stack

	def push(self, value: uint8) -> None:
		self.ram[0x100 + self.sp] = value
		self.sp = (self.sp - 1) % 256
		# self.instruction_logger.debug(f'Pushed ${value:02X}, sp={self.sp}')

	def push16(self, value: pointer16) -> None:
		self.ram[0x100 + self.sp : 0x100 + self.sp + 2] = value.to_bytes(2, byteorder='little')
		self.sp = (self.sp - 2) % 256
		# self.instruction_logger.debug(f'Pushed ${value:04X}, sp={self.sp}')

	def pull(self) -> uint8:
		self.sp = (self.sp + 1) % 256
		value = self.ram[0x100 + self.sp]
		# self.instruction_logger.debug(f'Pulled ${value:02X}, sp={self.sp}')
		return value

	def pull16(self) -> pointer16:
		self.sp = (self.sp + 2) % 256
		value = int.from_bytes(self.ram[0x100 + self.sp : 0x100 + self.sp + 2], byteorder='little')
		# self.instruction_logger.debug(f'Pulled ${value:04X}, sp={self.sp}')
		return value

	# Clock

	def _tick_clock(self, cycles: int):
		self.clock += cycles
		# TODO: does apu need tick too?
		self.ppu.tick_clock_fom_cpu(cycles)

	# Addressing modes
	# TODO: handle cycles inside addressing function
	# TODO: remove _val() versions and just replace with the call directly?

	def _addr_rel(self) -> int8:
		"""
		relative addressing mode, e.g. BCC rel
		:returns: signed value
		"""
		ret = self.read(self.pc)
		self.pc += 1
		ret = _signed(ret)
		self._addr_instr_log = f'{ret}'
		return ret

	def _addr_immediate(self) -> uint8:
		"""
		immediate addressing mode, e.g. LDA #oper
		:returns: value
		"""
		ret = self.read(self.pc)
		self._addr_instr_log = f'#${ret:02X}'
		self.pc += 1
		return ret

	def _addr_zeropage_addr(self) -> pointer16:
		"""
		zeropage addressing mode, e.g. LDA (zeropage)
		:returns: address
		"""
		addr = self.read(self.pc)
		self._addr_instr_log = f'${addr:02X}'
		self.pc += 1
		return addr

	def _addr_zeropage_val(self) -> uint8:
		"""
		zeropage addressing mode, e.g. LDA (zeropage)
		:returns: value
		"""
		return self.read(self._addr_zeropage_addr())

	def _addr_zeropage_x_addr(self) -> pointer16:
		"""
		zeropage,X addressing mode, e.g. LDA oper,X
		:returns: address (on zero-page)
		"""
		addr = self.read(self.pc)
		self._addr_instr_log = f'${addr:02X},X'
		addr = (addr + self.x) & 0xFF
		self.pc += 1
		return addr

	def _addr_zeropage_x_val(self) -> uint8:
		"""
		zeropage,X addressing mode, e.g. LDA oper,X
		:returns: value
		"""
		return self.ram[self._addr_zeropage_x_addr()]

	def _addr_zeropage_y_addr(self) -> pointer16:
		"""
		zeropage,X addressing mode, e.g. LDA oper,X
		:returns: address (on zero-page)
		"""
		addr = self.read(self.pc)
		self._addr_instr_log = f'${addr:02X},Y'
		addr = (addr + self.y) & 0xFF
		self.pc += 1
		return addr

	def _addr_zeropage_y_val(self) -> uint8:
		"""
		zeropage,X addressing mode, e.g. LDA oper,X
		:returns: value
		"""
		return self.ram[self._addr_zeropage_y_addr()]

	def _addr_absolute_addr(self) -> pointer16:
		"""
		absolute addressing mode, e.g. LDA oper
		:returns: address
		"""
		addr = self.read16(self.pc)
		self._addr_instr_log = f'${addr:04X}'
		self.pc += 2
		return addr

	def _addr_absolute_val(self) -> uint8:
		"""
		absolute addressing mode, e.g. LDA oper
		:returns: value
		"""
		return self.read(self._addr_absolute_addr())

	def _addr_absolute_x_addr(self) -> pointer16:
		"""
		absolute,x addressing mode, e.g. LDA oper,X
		:returns: address
		"""
		# TODO: 1 extra cycle if crossing page boundary
		addr = self.read16(self.pc)
		self._addr_instr_log = f'${addr:04X},X'
		addr += self.x
		self.pc += 2
		return addr

	def _addr_absolute_x_val(self) -> uint8:
		"""
		absolute,x addressing mode, e.g. LDA oper,X
		:returns: value
		"""
		return self.read(self._addr_absolute_x_addr())

	def _addr_absolute_y_addr(self) -> pointer16:
		"""
		absolute,x addressing mode, e.g. LDA oper,Y
		:returns: address
		"""
		# TODO: 1 extra cycle if crossing page boundary
		addr = self.read16(self.pc)
		self._addr_instr_log = f'${addr:04X},Y'
		addr += self.y
		self.pc += 2
		return addr

	def _addr_absolute_y_val(self) -> uint8:
		"""
		absolute,y addressing mode, e.g. LDA oper,Y
		:returns: value
		"""
		return self.read(self._addr_absolute_y_addr())

	def _addr_indirect(self) -> pointer16:
		"""
		(indirect) addressing mode, e.g. JMP (oper)
		:returns: value
		"""
		# JMP is the only instruction that uses this mode
		# TODO: emulate CPU bug if addr ends with 0xFF
		addr = self.read16(self.pc)
		self._addr_instr_log = f'(${addr:04X})'
		self.pc += 2
		return self.read16(addr)

	def _addr_indirect_x_addr(self) -> pointer16:
		"""
		(indirect,x) addressing mode, e.g. LDA (oper,X)
		:returns: address
		"""
		zp_addr = self.read(self.pc)
		self._addr_instr_log = f'(${zp_addr:02X},X)'
		zp_addr = (zp_addr + self.x) & 0xFF
		self.pc += 1
		# TODO optimization: can skip read16 and go directly to ram
		addr = self.read16(zp_addr)
		return addr

	def _addr_indirect_x_val(self) -> uint8:
		"""
		(indirect,x) addressing mode, e.g. LDA (oper,X)
		:returns: value
		"""
		return self.read(self._addr_indirect_x_addr())

	def _addr_indirect_y_addr(self) -> pointer16:
		"""
		(indirect),Y addressing mode, e.g. LDA (oper),Y
		:returns: address
		"""
		# TODO: 1 extra cycle if crossing page boundary
		zp_addr = self.read(self.pc)
		self._addr_instr_log = f'(${zp_addr:02X}),Y'
		self.pc += 1
		addr = self.read16(zp_addr) + self.y
		return addr

	def _addr_indirect_y_val(self) -> uint8:
		"""
		(indirect),Y addressing mode, e.g. LDA (oper),Y
		:returns: value
		"""
		return self.read(self._addr_indirect_y_addr())

	# VBLANK/NMI

	def vblank_start_callback(self) -> None:
		self.vblank_needs_handling = True

	def _handle_vblank(self) -> None:
		self.vblank_needs_handling = False
		self.clock = 0
		self.vblank_count += 1
		if self.ppu.nmi:
			self._handle_nmi()

	def _handle_nmi(self) -> None:
		self.push16(self.pc + 2)
		self.push(self.sr)
		self.b = True
		self.pc = self.nmi
		# TODO: is 7 ticks accurate? (I'm assuming it's same as BRK instruction)
		self._tick_clock(7)

	# Main process function

	def process_instruction(self) -> None:

		self.read_ppustatus_counter = max(0, self.read_ppustatus_counter - 1)

		if self.vblank_needs_handling:
			self._handle_vblank()

		clock_was = self.clock
		pc_was = self.pc
		sp_was = self.sp
		opcode = self.read(self.pc)
		self.pc += 1

		cycles = 0

		# If set, then Z & N flags will be updated
		result = None

		# TODO: use f-strings in more places, for more descriptive logging (self._addr_instr_log)
		instr_log = ''
		branched = None
		self._addr_instr_log = ''

		"""
		instruction set references:
		https://www.nesdev.org/wiki/Instruction_reference
		https://www.masswerk.at/6502/6502_instruction_set.html
		http://www.6502.org/users/obelisk/6502/instructions.html
		"""

		match opcode:

			case 0x69 | 0x65 | 0x75 | 0x6D | 0x7D | 0x79 | 0x61 | 0x71:
				instr_log = 'ADC'
				match opcode:
					case 0x69:
						cycles = 2
						value = self._addr_immediate()
					case 0x65:
						cycles = 3
						value = self._addr_zeropage_val()
					case 0x75:
						cycles = 4
						value = self._addr_zeropage_x_val()
					case 0x6D:
						cycles = 4
						value = self._addr_absolute_val()
					case 0x7D:
						cycles = 4
						value = self._addr_absolute_x_val()
					case 0x79:
						cycles = 4
						value = self._addr_absolute_y_val()
					case 0x61:
						cycles = 5
						value = self._addr_indirect_x_val()
					case 0x71:
						cycles = 6
						value = self._addr_indirect_y_val()

				result = self.a + value + int(self.c)
				self.c = (result > 255)
				self.v = bool((result ^ self.a) & (result ^ value) & 0x80)
				self.a = result = (result & 0xFF)

			case 0x29:
				# AND #oper
				instr_log = 'AND'
				cycles = 2
				val = self._addr_immediate()
				self.a &= val
				result = self.a

			case 0x25:
				# AND oper
				instr_log = 'AND'
				cycles = 3
				self.a &= self._addr_zeropage_val()
				result = self.a

			case 0x35:
				# AND oper,X
				instr_log = 'AND'
				cycles = 4
				self.a &= self._addr_zeropage_x_val()
				result = self.a

			case 0x2D:
				# AND oper
				instr_log = 'AND'
				cycles = 4
				self.a &= self._addr_absolute_val()
				result = self.a

			case 0x3D:
				# AND oper,X
				instr_log = 'AND'
				cycles = 4
				self.a &= self._addr_absolute_x_val()
				result = self.a

			case 0x39:
				# AND oper,y
				instr_log = 'AND'
				cycles = 4
				self.a &= self._addr_absolute_y_val()
				result = self.a

			case 0x21:
				# AND (oper,X)
				instr_log = 'AND'
				cycles = 6
				self.a &= self._addr_indirect_x_val()
				result = self.a

			case 0x31:
				# AND (oper),Y
				instr_log = 'AND'
				cycles = 5
				self.a &= self._addr_indirect_y_val()
				result = self.a

			case 0x0A:
				# ASL
				instr_log = 'ASL'
				cycles = 2
				self.c = bool(self.a & 0b1000_0000)
				result = self.a = (self.a << 1) & 0xFF

			case 0x06 | 0x16 | 0x0E | 0x1E:
				instr_log = 'ASL'
				match opcode:
					case 0x06:
						cycles = 5
						addr = self._addr_zeropage_addr()
					case 0x16:
						cycles = 6
						addr = self._addr_zeropage_x_addr()
					case 0x0E:
						cycles = 6
						addr = self._addr_absolute_addr()
					case 0x1E:
						cycles = 7
						addr = self._addr_absolute_x_addr()
				value = self.read(addr)
				self.c = bool(value & 0b1000_0000)
				result = (value << 1) & 0xFF
				self.write(addr, result)

			case 0x90:
				# BCC rel
				# TODO: add 1 to cycles if branch occurs on same page, add 2 to cycles if branch occurs to different page
				cycles = 2
				rel = self._addr_rel()
				instr_log = 'BCC'
				if not self.c:
					self.pc += rel
					branched = True
				else:
					branched = False

			case 0xB0:
				# BCS rel
				# TODO: add 1 to cycles if branch occurs on same page, add 2 to cycles if branch occurs to different page
				cycles = 2
				rel = self._addr_rel()
				instr_log = 'BCS'
				if self.c:
					self.pc += rel
					branched = True
				else:
					branched = False

			case 0xF0:
				# BEQ rel
				# TODO: add 1 to cycles if branch occurs on same page, add 2 to cycles if branch occurs to different page
				cycles = 2
				rel = self._addr_rel()
				instr_log = 'BEQ'
				if self.z:
					self.pc += rel
					branched = True
				else:
					branched = False

			case 0x24 | 0x2C:
				# BIT
				instr_log = 'BIT'
				if opcode == 0x24:
					cycles = 3
					result = self._addr_zeropage_val()
				else:
					cycles = 4
					result = self._addr_absolute_val()
				self.v = bool(result & 0b0100_0000)

			case 0x30:
				# BMI rel
				# TODO: add 1 to cycles if branch occurs on same page, add 2 to cycles if branch occurs to different page
				cycles = 2
				rel = self._addr_rel()
				instr_log = 'BMI'
				if self.n:
					self.pc += rel
					branched = True
				else:
					branched = False

			case 0xD0:
				# BNE
				# TODO: add 1 to cycles if branch occurs on same page, add 2 to cycles if branch occurs to different page
				cycles = 2
				rel = self._addr_rel()
				instr_log = 'BNE'
				if not self.z:
					self.pc += rel
					branched = True
				else:
					branched = False

			case 0x10:
				# BPL
				# TODO: add 1 to cycles if branch occurs on same page, add 2 to cycles if branch occurs to different page
				cycles = 2
				rel = self._addr_rel()
				instr_log = 'BPL'
				if not self.n:
					self.pc += rel
					branched = True
				else:
					branched = False

			case 0x00:
				# BRK
				instr_log = 'BRK'
				cycles = 7
				# Was already incremented once
				self.push16(self.pc + 1)
				self.push(self.sr)
				self.b = True
				self.pc = self.irq
				if self.stop_on_brk:
					raise StopIteration('Hit BRK instruction')

			case 0x50:
				# BVC
				# TODO: add 1 to cycles if branch occurs on same page, add 2 to cycles if branch occurs to different page
				cycles = 2
				rel = self._addr_rel()
				instr_log = 'BVC'
				if not self.v:
					self.pc += rel
					branched = True
				else:
					branched = False

			case 0x70:
				# BVS
				# TODO: add 1 to cycles if branch occurs on same page, add 2 to cycles if branch occurs to different page
				cycles = 2
				rel = self._addr_rel()
				instr_log = 'BVS'
				if self.v:
					self.pc += rel
					branched = True
				else:
					branched = False

			case 0x18:
				# CLC
				instr_log = 'CLC'
				cycles = 2
				self.c = False

			case 0xD8:
				# CLD
				instr_log = 'CLD'
				cycles = 2
				self.d = False

			case 0x58:
				# CLI
				instr_log = 'CLI'
				cycles = 2
				self.i = False

			case 0xB8:
				# CLV
				instr_log = 'CLV'
				cycles = 2
				self.v = False

			case 0xC9 | 0xC5 | 0xD5 | 0xCD | 0xDD | 0xD9 | 0xC1 | 0xD1:
				# CMP
				instr_log = 'CMP'
				match opcode:
					case 0xC9:
						cycles = 2
						value = self._addr_immediate()
					case 0xC5:
						cycles = 3
						value = self._addr_zeropage_val()
					case 0xD5:
						cycles = 4
						value = self._addr_zeropage_x_val()
					case 0xCD:
						cycles = 4
						value = self._addr_absolute_val()
					case 0xDD:
						cycles = 4
						value = self._addr_absolute_x_val()
					case 0xD9:
						cycles = 4
						value = self._addr_absolute_y_val()
					case 0xC1:
						cycles = 6
						value = self._addr_indirect_x_val()
					case 0xD1:
						cycles = 5
						value = self._addr_indirect_y_val()
				self.c = (self.a >= value)
				result = (self.a - value) % 256
				assert 0 <= result < 256

			case 0xE0 | 0xE4 | 0xEC:
				# CPX
				instr_log = 'CPX'
				match opcode:
					case 0xE0:
						value = self._addr_immediate()
					case 0xE4:
						value = self._addr_zeropage_val()
					case 0xEC:
						value = self._addr_absolute_val()
				self.c = (self.x >= value)
				result = (self.x - value) % 256
				assert 0 <= result < 256

			case 0xC0 | 0xC4 | 0xCC:
				# CPY
				instr_log = 'CPY'
				match opcode:
					case 0xC0:
						value = self._addr_immediate()
					case 0xC4:
						value = self._addr_zeropage_val()
					case 0xCC:
						value = self._addr_absolute_val()
				self.c = (self.y >= value)
				result = (self.y - value) % 256
				assert 0 <= result < 256

			case 0xC6 | 0xD6 | 0xCE | 0xDE:
				# DEC
				instr_log = 'DEC'
				match opcode:
					case 0xC6:
						cycles = 5
						addr = self._addr_zeropage_addr()
					case 0xD6:
						cycles = 6
						addr = self._addr_zeropage_x_addr()
					case 0xCE:
						cycles = 6
						addr = self._addr_absolute_addr()
					case 0xDE:
						cycles = 7
						addr = self._addr_absolute_x_addr()
				value = self.read(addr)
				result = (value - 1) % 256
				self.write(addr, result)

			case 0xCA:
				# DEX
				instr_log = 'DEX'
				cycles = 2
				result = self.x = (self.x - 1) % 256

			case 0x88:
				# DEY
				instr_log = 'DEY'
				cycles = 2
				result = self.y = (self.y - 1) % 256

			case 0x49 | 0x45 | 0x55 | 0x4D | 0x5D | 0x59 | 0x41 | 0x51:
				# EOR
				instr_log = 'EOR'
				match opcode:
					case 0x49:
						cycles = 2
						value = self._addr_immediate()
					case 0x45:
						cycles = 3
						value = self._addr_zeropage_val()
					case 0x55:
						cycles = 4
						value = self._addr_zeropage_x_val()
					case 0x4D:
						cycles = 4
						value = self._addr_absolute_val()
					case 0x5D:
						cycles = 4
						value = self._addr_absolute_x_val()
					case 0x59:
						cycles = 4
						value = self._addr_absolute_y_val()
					case 0x41:
						cycles = 6
						value = self._addr_indirect_x_val()
					case 0x51:
						cycles = 5
						value = self._addr_indirect_y_val()
				result = self.a = self.a ^ value

			case 0xE6:
				# INC oper (zeropage)
				cycles = 5
				addr = self._addr_zeropage_addr()
				instr_log = 'INC'
				result = (self.ram[addr] + 1) & 0xFF
				self.ram[addr] = result

			case 0xF6:
				# INC oper,X (zeropage,X)
				instr_log = 'INC'
				cycles = 6
				addr = self._addr_zeropage_x_addr()
				result = (self.ram[addr] + 1) & 0xFF
				self.ram[addr] = result

			case 0xEE:
				# INC oper (absolute)
				cycles = 6
				addr = self._addr_absolute_addr()
				instr_log = 'INC'
				result = (self.read(addr) + 1) & 0xFF
				self.write(addr, result)

			case 0xFE:
				# INC oper,X (absolute,X)
				instr_log = 'INC'
				cycles = 7
				addr = self._addr_absolute_x_addr()
				result = (self.read(addr) + 1) & 0xFF
				self.write(addr, result)

			case 0xE8:
				# INX
				instr_log = 'INX'
				cycles = 2
				result = self.x = (self.x + 1) & 0xFF

			case 0xC8:
				# INY
				instr_log = 'INY'
				cycles = 2
				result = self.y = (self.y + 1) & 0xFF

			case 0x4C:
				# JMP oper (absolute)
				cycles = 3
				self.pc = self.read16(self.pc)
				instr_log = f'JMP ${self.pc:04X}'

			case 0x6C:
				# JMP (oper) (indirect)
				instr_log = 'JMP'
				cycles = 5
				self.pc = self._addr_indirect()

			case 0x20:
				# JSR
				cycles = 6
				# We've already incremented PC by 1, so add 1 instead of 2
				self.push16(self.pc + 1)
				self.pc = self.read16(self.pc)
				instr_log = f'JSR ${self.pc:04X}'

			case 0xA9 | 0xA5 | 0xB5 | 0xAD | 0xBD | 0xB9 | 0xA1 | 0xB1:
				# LDA
				instr_log = 'LDA'
				match opcode:
					case 0xA9:
						cycles = 2
						result = self._addr_immediate()
					case 0xA5:
						cycles = 3
						result = self._addr_zeropage_val()
					case 0xB5:
						cycles = 4
						result = self._addr_zeropage_x_val()
					case 0xAD:
						cycles = 4
						result = self._addr_absolute_val()
					case 0xBD:
						cycles = 4
						result = self._addr_absolute_x_val()
					case 0xB9:
						cycles = 4
						result = self._addr_absolute_y_val()
					case 0xA1:
						cycles = 6
						result = self._addr_indirect_x_val()
					case 0xB1:
						cycles = 5
						result = self._addr_indirect_y_val()
				self.a = result

			case 0xA2:
				# LDX #oper
				cycles = 2
				result = self.x = self._addr_immediate()
				instr_log = 'LDX'

			case 0xA6:
				# LDX oper
				instr_log = 'LDX'
				cycles = 3
				result = self.x = self._addr_zeropage_val()

			case 0xB6:
				# LDX oper,Y
				instr_log = 'LDX'
				cycles = 4
				result = self.x = self._addr_zeropage_y_val()

			case 0xAE:
				# LDX oper
				instr_log = 'LDX'
				cycles = 4
				result = self.x = self._addr_absolute_val()

			case 0xBE:
				# LDX oper,Y
				instr_log = 'LDX'
				cycles = 4
				result = self.x = self._addr_absolute_y_val()

			case 0xA0:
				# LDY #oper
				cycles = 2
				result = self.y = self._addr_immediate()
				instr_log = 'LDY'

			case 0xA4:
				# LDY oper
				instr_log = 'LDY'
				cycles = 3
				result = self.y = self._addr_zeropage_val()

			case 0xB4:
				# LDY oper,X
				instr_log = 'LDY'
				cycles = 4
				result = self.y = self._addr_zeropage_x_val()

			case 0xAC:
				# LDY oper
				instr_log = 'LDY'
				cycles = 4
				result = self.y = self._addr_absolute_val()

			case 0xBC:
				# LDY oper,X
				instr_log = 'LDY'
				cycles = 4
				result = self.y = self._addr_absolute_x_val()

			case 0x4A:
				# LSR
				instr_log = 'LSR'
				cycles = 2
				val = self.a
				self.c = val & 0x1
				result = self.a = (val >> 1)

			case 0x46 | 0x56 | 0x4E | 0x5E:
				# LSR
				instr_log = 'LSR'
				match opcode:
					case 0x46:
						cycles = 5
						addr = self._addr_zeropage_addr()
					case 0x56:
						cycles = 6
						addr = self._addr_zeropage_x_addr()
					case 0x4E:
						cycles = 6
						addr = self._addr_absolute_addr()
					case 0x5E:
						cycles = 7
						addr = self._addr_absolute_x_addr()
				val = self.read(addr)
				self.c = val & 0x1
				result = (val >> 1)
				self.write(addr, result)

			case 0xEA:
				# NOP
				instr_log = 'NOP'
				cycles = 2

			case 0x09 | 0x05 | 0x15 | 0x0D | 0x1D | 0x19 | 0x01 | 0x11:
				# ORA
				instr_log = 'ORA'
				match opcode:
					case 0x09:
						cycles = 2
						val = self._addr_immediate()
					case 0x05:
						cycles = 3
						val = self._addr_zeropage_val()
					case 0x15:
						cycles = 4
						val = self._addr_zeropage_x_val()
					case 0x0D:
						cycles = 4
						val = self._addr_absolute_val()
					case 0x1D:
						cycles = 4
						val = self._addr_absolute_x_val()
					case 0x19:
						cycles = 4
						val = self._addr_absolute_y_val()
					case 0x01:
						cycles = 6
						val = self._addr_indirect_x_val()
					case 0x11:
						cycles = 5
						val = self._addr_indirect_y_val()
				result = self.a = (val | self.a)

			case 0x48:
				# PHA
				instr_log = 'PHA'
				cycles = 3
				self.push(self.a)

			case 0x08:
				# PHP
				instr_log = 'PHP'
				cycles = 3
				self.push(self.sr)

			case 0x68:
				# PLA
				instr_log = 'PLA'
				cycles = 4
				result = self.a = self.pull()

			case 0x28:
				# PLP
				instr_log = 'PLP'
				cycles = 4
				self.sr = self.pull()

			case 0x2A:
				# ROL
				instr_log = 'ROL'
				cycles = 2
				c_new = bool(self.a & 0b1000_0000)
				result = self.a = ((self.a << 1) | int(self.c)) & 0xFF
				self.c = c_new

			case 0x26 | 0x36 | 0x2E | 0x3E:
				# ROL
				instr_log = 'ROL'
				match opcode:
					case 0x26:
						cycles = 5
						addr = self._addr_zeropage_addr()
					case 0x36:
						cycles = 6
						addr = self._addr_zeropage_x_addr()
					case 0x2E:
						cycles = 6
						addr = self._addr_absolute_addr()
					case 0x3E:
						cycles = 7
						addr = self._addr_absolute_x_addr()
				value = self.read(addr)
				c_new = bool(value & 0b1000_0000)
				result = ((value << 1) | (1 if self.c else 0)) & 0xFF
				self.write(addr, result)
				self.c = c_new

			case 0x6A:
				# ROR
				instr_log = 'ROR'
				cycles = 2
				c_new = (self.a & 0x01)
				result = self.a = ((self.a >> 1) | (0b1000_0000 if self.c else 0)) & 0xFF
				self.c = c_new

			case 0x66 | 0x76 | 0x6E | 0x7E:
				# ROR
				instr_log = 'ROR'
				match opcode:
					case 0x66:
						cycles = 5
						addr = self._addr_zeropage_addr()
					case 0x76:
						cycles = 6
						addr = self._addr_zeropage_x_addr()
					case 0x6E:
						cycles = 6
						addr = self._addr_absolute_addr()
					case 0x7E:
						cycles = 7
						addr = self._addr_absolute_x_addr()
				value = self.read(addr)
				c_new = (value & 0x01)
				result = ((value >> 1) | (0b1000_0000 if self.c else 0)) & 0xFF
				self.write(addr, result)
				self.c = c_new

			case 0x40:
				# RTI
				instr_log = 'RTI'
				cycles = 6
				self.sr = self.pull()
				self.pc = self.pull16()

			case 0x60:
				# RTS
				instr_log = 'RTS'
				cycles = 6
				self.pc = self.pull16() + 1

			case 0xE9 | 0xE5 | 0xF5 | 0xED | 0xFD | 0xF9 | 0xE1 | 0xF1:
				# SBC
				instr_log = 'SBC'
				match opcode:
					case 0xE9:
						cycles = 2
						value = self._addr_immediate()
					case 0xE5:
						cycles = 3
						value = self._addr_zeropage_val()
					case 0xF5:
						cycles = 4
						value = self._addr_zeropage_x_val()
					case 0xED:
						cycles = 4
						value = self._addr_absolute_val()
					case 0xFD:
						cycles = 4
						value = self._addr_absolute_x_val()
					case 0xF9:
						cycles = 4
						value = self._addr_absolute_y_val()
					case 0xE1:
						cycles = 6
						value = self._addr_indirect_x_val()
					case 0xF1:
						cycles = 5
						value = self._addr_indirect_y_val()
				result = self.a + (~value) + int(self.c)				
				self.c = result >= 0
				self.v = bool((result ^ self.a) & (result ^ value) & 0x80)
				self.a = result = (result % 256)

			case 0x38:
				# SEC
				instr_log = 'SEC'
				cycles = 2
				self.c = True

			case 0xF8:
				# SED
				instr_log = 'SED'
				cycles = 2
				self.d = True

			case 0x78:
				# SEI
				instr_log = 'SEI'
				cycles = 2
				self.i = True

			case 0x85 | 0x95 | 0x8D | 0x9D | 0x99 | 0x81 | 0x91:
				# STA
				instr_log = 'STA'
				match opcode:
					case 0x85:
						cycles = 3
						addr = self._addr_zeropage_addr()
					case 0x95:
						cycles = 4
						addr = self._addr_zeropage_x_addr()
					case 0x8D:
						cycles = 4
						addr = self._addr_absolute_addr()
					case 0x9D:
						cycles = 5
						addr = self._addr_absolute_x_addr()
					case 0x99:
						cycles = 5
						addr = self._addr_absolute_y_addr()
					case 0x81:
						cycles = 6
						addr = self._addr_indirect_x_addr()
					case 0x91:
						cycles = 6
						addr = self._addr_indirect_y_addr()
				self.write(addr, self.a)

			case 0x86:
				# STX oper
				instr_log = 'STX'
				cycles = 3
				addr = self._addr_zeropage_addr()
				self.write(addr, self.x)

			case 0x96:
				# STX oper,Y
				instr_log = 'STX'
				cycles = 4
				addr = self._addr_zeropage_y_addr()
				self.write(addr, self.x)

			case 0x8E:
				# STX oper
				instr_log = 'STX'
				cycles = 4
				addr = self._addr_absolute_addr()
				self.write(addr, self.x)

			case 0x84:
				# STY oper
				instr_log = 'STY'
				cycles = 3
				addr = self._addr_zeropage_addr()
				self.write(addr, self.y)

			case 0x94:
				# STX oper,X
				instr_log = 'STY'
				cycles = 4
				addr = self._addr_zeropage_x_addr()
				self.write(addr, self.y)

			case 0x8C:
				# STY oper
				instr_log = 'STY'
				cycles = 4
				addr = self._addr_absolute_addr()
				self.write(addr, self.y)

			case 0xAA:
				# TAX
				instr_log = 'TAX'
				cycles = 2
				result = self.x = self.a

			case 0xA8:
				# TAY
				instr_log = 'TAY'
				cycles = 2
				result = self.y = self.a

			case 0xBA:
				# TSX
				instr_log = 'TSX'
				cycles = 2
				result = self.x = self.sp

			case 0x8A:
				# TXA
				instr_log = 'TXA'
				cycles = 2
				result = self.a = self.x

			case 0x9A:
				# TXS
				instr_log = 'TXS'
				cycles = 2
				result = self.sp = self.x

			case 0x98:
				# TYA
				instr_log = 'TYA'
				cycles = 2
				result = self.a = self.y

			case 0x02 | 0x12 | 0x22 | 0x32 | 0x42 | 0x52 | 0x62 | 0x72 | 0x92 | 0xB2 | 0xD2 | 0xF2:
				raise Exception(f'Invalid instruction (JAM): 0x{opcode:02X}')

			case _:
				raise NotImplementedError(f'CPU instruction 0x{opcode:02X} not implemented')

		if result is not None:
			self.z = (result == 0)
			self.n = bool(result & 0b1000_0000)

		if self.instruction_logger:

			# TODO: is it better to auto indent based on stack pointer, or manual inc/dec based on interrupts/JSR/RTI/RTS
			# num_indent = (255 - sp_was) if (sp_was > 0) else 0
			# num_indent = (255 - sp_was) % 32
			num_indent = (256 - sp_was) % 32

			indent = ' ' * num_indent
			sp = self.sp

			if self._addr_instr_log:
				instr_log += ' ' + self._addr_instr_log

			if False:
				msg = (
					f't={clock_was:5}, pc=0x{pc_was:04X}, instr=0x{opcode:02X}, {indent + instr_log:48} '
					f'a=0x{self.a:02X} x=0x{self.x:02X} y=0x{self.y:02X} sp={self.sp:3} {self.sr_str}'
				)
			else:
				# msg = f'{clock_was:5}, pc=0x{pc_was:04X}, instr=0x{opcode:02X}, {indent + instr_log:48} {self.sr_str}'
				msg = (
					f'{self.ppu.frame_count}, ({self.ppu.row:3}, {self.ppu.col:3}); '
					f'pc=0x{pc_was:04X}, instr=0x{opcode:02X}, {indent + instr_log:48} {self.sr_str}'
				)

			if branched is not None:
				msg += ' (branched)' if branched else ' (no branch)'

			if result is not None:
				msg += f' (result=0x{result:02X})'

			if sp != sp_was:
				msg += f'; SP {sp_was} -> {sp}'

			self.instruction_logger.debug(msg)

		# TODO: technically, this should happen before result happens
		self._tick_clock(cycles)
