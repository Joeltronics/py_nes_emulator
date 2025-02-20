#!/usr/bin/env python3

from math import ceil
import logging
from typing import Callable, Final

import numpy as np

from nes.graphics_utils import chr_to_array, chr_to_stacked, grey_to_rgb, load_palette_file, upscale, draw_rectangle
from nes.rom import INesHeader
from nes.types import uint8, pointer16


logger = logging.getLogger(__name__)


COLUMNS: Final[int] = 340

VBLANK_START_ROW: Final[int] = 240
VBLANK_END_ROW: Final[int] = 260
TOTAL_ROWS: Final[int] = 262

NAMETABLE_A_VRAM_START: Final[pointer16] = 0x000
NAMETABLE_B_VRAM_START: Final[pointer16] = 0x400

NAMETABLE_LAYOUT_HORIZONTAL: Final[tuple[int, int, int, int]] = (
	NAMETABLE_A_VRAM_START, NAMETABLE_A_VRAM_START, NAMETABLE_B_VRAM_START, NAMETABLE_B_VRAM_START)
NAMETABLE_LAYOUT_VERTICAL: Final[tuple[int, int, int, int]] = (
	NAMETABLE_A_VRAM_START, NAMETABLE_B_VRAM_START, NAMETABLE_A_VRAM_START, NAMETABLE_B_VRAM_START)

SPRITE_ZERO_HIT_NONE: Final[tuple[int, int]] = (TOTAL_ROWS + 1, COLUMNS)


class Ppu:
	def __init__(
			self,
			rom_chr: bytes,
			rom_header: INesHeader,
			):

		self.rom_chr: Final[bytes] = rom_chr

		self._chr_tiles_mask = chr_to_stacked(self.rom_chr) > 0

		self.nametable_layout: Final[tuple[int, int, int, int]] = (
			NAMETABLE_LAYOUT_VERTICAL if rom_header.vertical_mirroring else NAMETABLE_LAYOUT_HORIZONTAL
		)

		self.vram: Final[bytearray] = bytearray(2048)
		self.palette_ram: Final[bytearray] = bytearray(32)
		self.oam: Final[bytearray] = bytearray(256)

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

		self.sprite_zero_hit_loc: tuple[int, int] = SPRITE_ZERO_HIT_NONE

		self.odd_frame: bool = False

		self.vblank_start_callback: Callable[[], None] | None = None
		self.vblank_end_callback: Callable[[], None] | None = None

		self.debug_status_im = np.zeros((TOTAL_ROWS, 3), dtype=np.uint8)

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

	def done_rendering(self) -> None:
		"""
		Indicate that rendering a frame is complete
		"""
		self.debug_status_im[:] = 31
		self.debug_status_im[VBLANK_START_ROW:, ...] = (127, 127, 127)

	def _tick_clock(self, cycles: int) -> None:
		self.col += cycles
		while self.col > COLUMNS:
			self.col -= COLUMNS
			self._finish_row(self.row)
			self.row = (self.row + 1) % TOTAL_ROWS

			if self.row == 0:
				self.frame_count += 1
				if self.odd_frame:
					self.col += 1
				self.odd_frame = not self.odd_frame

	def _finish_row(self, row_num: int) -> None:

		assert row_num < TOTAL_ROWS

		if row_num < 240:
			# TODO accuracy: fire this as soon as we hit the relevant pixel, not at the end of the row
			if self.sprite_zero_hit_loc[0] == row_num:
				logger.debug(f'Sprite zero hit on row {row_num}')
				self.ppustatus |= 0b0100_0000
				self.debug_status_im[row_num, 1] = 255

		elif row_num == VBLANK_START_ROW:
			# TODO accuracy: technically this occurs 1 PPU clock later
			self._vblank_start()

		elif row_num == VBLANK_END_ROW:
			# TODO accuracy: technically this occurs 1 PPU clock later
			self._vblank_end()

	def _calculate_sprite_zero_hit(self) -> tuple[int, int]:
		"""
		Calculate pixel where sprite zero hit flag should get set, based on current data
		:returns: (y, x); if sprite zero never gets hit, then returns out of bounds coordinate (SPRITE_ZERO_HIT_NONE)
		"""

		ppumask = self.ppumask

		# TODO: PPUMASK bits 1 or 2

		# If sprite or BG rendering is disabled, we do not hit
		if (ppumask & 0b0001_1000) != 0b0001_1000:
			return SPRITE_ZERO_HIT_NONE

		sprite_y = self.oam[0] + 1
		if sprite_y >= 240:
			return SPRITE_ZERO_HIT_NONE

		sprite_tile_idx = self.oam[1]
		sprite_flags = self.oam[2]
		sprite_x = self.oam[3]

		tile = self._chr_tiles_mask[sprite_tile_idx]

		if sprite_flags & 0b1000_0000:
			tile = np.flipud(tile)

		if sprite_flags & 0b0100_0000:
			tile = np.fliplr(tile)

		# TODO: load background tiles around this area, np.logical_and() these two together
		# scroll_x = self.scroll_x
		# scroll_y = self.scroll_y

		# Find first non-zero pixel

		if not tile.any():
			return SPRITE_ZERO_HIT_NONE

		tile_y, tile_x = np.unravel_index(np.argmax(tile), tile.shape)

		x = sprite_x + tile_x
		y = sprite_y + tile_y

		# x=255 does not trigger sprite 0 hit
		# https://www.nesdev.org/wiki/PPU_OAM#Sprite_0_hits
		if x >= 255 or y >= 240:
			return SPRITE_ZERO_HIT_NONE

		return y, x

	def tick_until_ppustatus_change(self) -> None:
		logger.debug('Waiting for next PPUSTATUS change')
		# Tick clock until next PPUSTATUS change
		ppustatus = self.ppustatus

		# TODO: store which rows we've skipped, to display for debugging

		row_start = self.row

		# TODO optimization: Instead of ticking 1 row at a time, calculate when the next PPUSTATUS change will happen
		# and jump straight there (although with the way tick_clock works right now, this might not be that much of an
		# optimization)
		while self.ppustatus == ppustatus:
			# Tick ahead 1 row
			self._tick_clock(COLUMNS)

		row_end = self.row

		assert row_end != row_start

		if row_end >= row_start:
			self.debug_status_im[row_start:row_end, 2] = 255
		else:
			self.debug_status_im[row_start:, 2] = 255
			self.debug_status_im[:row_end, 2] = 255

	def _vblank_start(self):
		# Set vblank
		self.ppustatus |= 0b1000_0000
		if self.vblank_nmi_enable:
			logger.debug(f'Frame {self.frame_count} VBLANK start (NMI enabled)')
			self.nmi = True
		else:
			logger.debug(f'Frame {self.frame_count} VBLANK start (NMI disabled)')

		if self.vblank_start_callback:
			self.vblank_start_callback()

	def _vblank_end(self):
		# Disable vblank, sprite0, overflow
		logger.debug('VBLANK end')
		self.ppustatus = 0
		self.nmi = False

		if self.vblank_end_callback:
			self.vblank_end_callback()

		self.sprite_zero_hit_loc = self._calculate_sprite_zero_hit()

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

		# https://forums.nesdev.org/viewtopic.php?t=7890
		rendering = (not self.vblank) and (self.ppumask & 0b0001_1000)

		# FIXME: PPUSCROLL & PPUADDR share an internal register (as well as 2 bits of PPUCTRL)
		# https://www.nesdev.org/wiki/PPU_scrolling
		# It also sounds like vertical scroll gets delayed until next frame, except with hacks via 0x2006

		match addr:
			case 0x2000:
				# PPUCTRL
				# Can be modified while rendering
				logger.debug(f'Setting PPUCTRL=0x{value:02X}')
				self.ppuctrl = value
			case 0x2001:
				# PPUMASK
				# Can be modified while rendering
				logger.debug(f'Setting PPUMASK=0x{value:02X}')
				self.ppumask = value
			case 0x2003:
				# OAMADDR
				# Should not be modified while rendering
				if rendering:
					raise NotImplementedError('Behavior of writing OAMADDR while rendering is not implemented')
				self.oamaddr = value
			case 0x2004:
				# OAMDATA
				# Should not be modified while rendering
				raise NotImplementedError('Manually writing OAMDATA is not yet supported')

			case 0x2005:
				# PPUSCROLL
				# Can be modified while rendering
				if not self.write_latch:
					# 1st write: X
					logger.debug(f'Setting PPUSCROLL X={value}')
					self.scroll_x = value
				else:
					# 2nd write: Y
					# TODO: if rendering, do not apply until write to 2006
					logger.debug(f'Setting PPUSCROLL Y={value}')
					self.scroll_y = value
				self.write_latch = not self.write_latch

			case 0x2006:
				# PPUADDR
				# TODO: behavior while rendering
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
				# Should not be modified while rendering
				if rendering:
					raise NotImplementedError('Behavior of writing PPUDATA while rendering is not implemented')
				self.write(self.ppuaddr, value)
				self.ppuaddr += self.ppuaddr_increment

			case _:
				raise NotImplementedError(f'TODO: support writing PPU register ${addr:04X}')

		self.debug_status_im[self.row, 0] = 255

		if rendering and (not self.sprite_zero_hit):
			# If updating oustide VBLANK, update sprite zero location
			self.sprite_zero_hit_loc = self._calculate_sprite_zero_hit()

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
			idx = addr % 0x20
			if idx >= 0x10 and idx % 4 == 0:
				# Palette entry 0 is shared between sprite & BG
				# This neeeded for Super Mario Bros to work properly
				idx -= 0x10
			self.palette_ram[idx] = value

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
		# TODO: do this step by step instead of all at once, like a real NES
		# TODO: not sure of behavior if called outside of VBLANK
		# If it's allowed, update self.sprite_zero_hit_loc
		assert len(data) == len(self.oam)
		self.oam[:] = data

		row_start = self.row
		row_end = row_start + ceil(513 * 3 / COLUMNS)

		self.debug_status_im[row_start:row_end, 1] = 255
