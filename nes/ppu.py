#!/usr/bin/env python3

import logging
from typing import Callable, Final

from nes.rom import INesHeader
from nes.types import uint8, pointer16

logger = logging.getLogger('ppu')

NAMETABLE_A_VRAM_START: Final[pointer16] = 0x000
NAMETABLE_B_VRAM_START: Final[pointer16] = 0x400

NAMETABLE_LAYOUT_HORIZONTAL: Final[tuple[int, int, int, int]] = (
	NAMETABLE_A_VRAM_START, NAMETABLE_A_VRAM_START, NAMETABLE_B_VRAM_START, NAMETABLE_B_VRAM_START)
NAMETABLE_LAYOUT_VERTICAL: Final[tuple[int, int, int, int]] = (
	NAMETABLE_A_VRAM_START, NAMETABLE_B_VRAM_START, NAMETABLE_A_VRAM_START, NAMETABLE_B_VRAM_START)


class Ppu:
	def __init__(self, rom_chr: bytes, rom_header: INesHeader):

		self.rom_chr: Final[bytes] = rom_chr

		self.nametable_layout: Final[tuple[int, int, int, int]] = (
			NAMETABLE_LAYOUT_VERTICAL if rom_header.vertical_mirroring else NAMETABLE_LAYOUT_HORIZONTAL
		)

		self.vram: Final[bytearray] = bytearray(2048)
		self.palette_ram: Final[bytearray] = bytearray(32)

		self.frame_count: int = 0
		self.row: int = 0
		self.col: int = 0

		# Registers
		self.ppuctrl: uint8 = 0  # $2000
		self.ppumask: uint8 = 0  # $2001
		self.ppustatus: uint8 = 0  # $2002
		self.oamaddr: uint8 = 0  # $2003
		self.scroll_x: uint8 = 0  # $ 2005
		self.scroll_y: uint8 = 0  # $ 2005
		self.ppuaddr: pointer16 = 0  # $2006
		self.ppudata_read_buffer: uint8 = 0  # $2007

		self.write_latch: bool = False

		self.nmi: bool = False

		self.odd_frame: bool = False

		self.vblank_start_callback: Callable[[], None] | None = None

	@property
	def vblank_nmi_enable(self) -> bool:
		return bool(self.ppuctrl & 0b1000_0000)

	@property
	def vblank(self) -> bool:
		return bool(self.ppustatus & 0b1000_0000)

	@property
	def sprite_zero_hit(self) -> bool:
		return bool(self.ppustatus & 0b0100_0000)

	@property
	def sprite_overflow(self) -> bool:
		return bool(self.ppustatus & 0b0010_0000)

	@property
	def ppuaddr_increment(self) -> int:
		return 32 if (self.ppuctrl & 0b0000_0100) else 1

	def tick_clock_fom_cpu(self, cpu_cycles: int) -> None:
		ppu_cycles = 3 * cpu_cycles
		self._tick_clock(ppu_cycles)

	def _tick_clock(self, cycles: int) -> None:
		self.col += cycles
		while self.col > 340:
			self.col -= 340
			self._finish_row(self.row)
			self.row = (self.row + 1) % 262

			if self.row == 0:
				self.frame_count += 1
				if self.odd_frame:
					self.col += 1
				self.odd_frame = not self.odd_frame

	def _finish_row(self, row_num: int) -> None:

		assert row_num <= 261

		if row_num < 240:
			pass  # TODO: render row

		elif row_num == 240:
			# TODO accuracy: technically this occurs 1 PPU clock later
			self._vblank_start()

		elif row_num == 260:
			# TODO accuracy: technically this occurs 1 PPU clock later
			self._vblank_end()

	def wait_for_ppustatus_change(self) -> None:
		pass  # TODO: tick clock until next PPUSTATUS change
		# raise NotImplementedError('TODO: wait_for_ppustatus_change()')

	def _vblank_start(self):
		# Set vblank
		self.ppustatus |= 0b1000_0000
		if self.vblank_nmi_enable:
			logger.debug('VBLANK start (NMI enabled)')
			self.nmi = True
		else:
			logger.debug('VBLANK start (NMI disabled)')
		
		if self.vblank_start_callback:
			self.vblank_start_callback()

	def _vblank_end(self):
		# Disable vblank, sprite0, overflow
		logger.debug('VBLANK end')
		self.ppustatus = 0
		self.nmi = False

	def read_reg_from_cpu(self, addr: pointer16) -> uint8:
		"""
		Read register in the range 0x2000-0x2007
		"""

		match addr:
			case 0x2000:
				# PPUCTRL
				return self.ppuctrl
			case 0x2001:
				# PPUMASK
				return self.ppumask
			case 0x2002:
				# PPUSTATUS
				self.write_latch = False
				return self.ppustatus
			case 0x2007:
				# PPUDATA
				ret = self.ppudata_read_buffer
				self.ppudata_read_buffer = self.read(self.ppuaddr)
				self.ppuaddr += self.ppuaddr_increment
				return ret
			case _:
				raise NotImplementedError(f'TODO: support reading PPU register ${addr:04X}')

	def write_reg_from_cpu(self, addr: pointer16, value: uint8) -> None:
		"""
		Write register in the range 0x2000-0x2007
		"""

		match addr:
			case 0x2000:
				# PPUCTRL
				logger.debug(f'Setting PPUCTRL=0x{value:02X}')
				self.ppuctrl = value
			case 0x2001:
				# PPUMASK
				logger.debug(f'Setting PPUMASK=0x{value:02X}')
				self.ppumask = value
			case 0x2003:
				# OAMADDR
				self.oamaddr = value
			case 0x2004:
				# OAMDATA
				raise NotImplementedError('Manually writing OAMDATA is not yet supported')

			case 0x2005:
				# PPUSCROLL
				if not self.write_latch:
					# 1st write: X
					logger.debug(f'Setting PPUSCROLL X={value}')
					self.scroll_x = value
				else:
					# 2nd write: Y
					logger.debug(f'Setting PPUSCROLL Y={value}')
					self.scroll_y = value
				self.write_latch = not self.write_latch

			case 0x2006:
				# PPUADDR
				if not self.write_latch:
					# 1st write: MSB
					self.ppuaddr = ((value & 0x3F) << 8) | (self.ppuaddr & 0x00FF)
				else:
					# 2nd write: LSB
					self.ppuaddr = (self.ppuaddr & 0xFF00) | value
					logger.debug(f'Set PPUADDR=${self.ppuaddr:04X}')
				self.write_latch = not self.write_latch

			case 0x2007:
				# PPUDATA
				self.write(self.ppuaddr, value)
				self.ppuaddr += self.ppuaddr_increment

			case _:
				raise NotImplementedError(f'TODO: support writing PPU register ${addr:04X}')

	def nametable_vram_addr(self, addr: pointer16) -> int:
		nametable_idx, addr_low = divmod(addr & 0x0FFF, 0x400)
		return addr_low + self.nametable_layout[nametable_idx]

	def write(self, addr: pointer16, value: uint8) -> None:

		if addr < 0x2000:
			# CHR
			raise NotImplementedError('Writing to CHR (e.g. for CHR-RAM) is not supported')

		elif addr < 0x3000:
			# Nametable
			self.vram[self.nametable_vram_addr(addr)] = value

		elif addr < 0x3F00:
			# Unused
			pass

		elif addr < 0x4000:
			# Palette RAM
			self.palette_ram[addr % 0x20] = value

		else:
			raise AssertionError(f'Invalid PPU address: ${addr:04X}')

	def read(self, addr: pointer16) -> uint8:
		if addr < 0x2000:
			# CHR
			return self.rom_chr[addr % len(self.rom_chr)]

		elif addr < 0x3000:
			# Nametable
			return self.vram[self.nametable_vram_addr(addr)]

		elif addr < 0x3F00:
			# Unused
			return 0

		elif addr < 0x4000:
			# Palette RAM indexes
			raise NotImplementedError('TODO: ppu.read() palette RAM')

		raise AssertionError(f'Invalid PPU address: ${addr:04X}')

	def oam_dma(self, data: bytes) -> None:
		"""
		Start an OAM DMA
		"""
		pass  # TODO
