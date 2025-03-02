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


def _sprite_zero_hit_load_sprite(
		*,
		oam: bytes | bytearray,
		ppuctrl: uint8,
		chr_tiles_8x8: np.ndarray,
		chr_tiles_8x16: np.ndarray,
		) -> tuple[np.ndarray, int, int] | tuple[None, None, None]:
	"""
	Load sprite 0, and adjust for flip flags

	:returns: (tile, X, Y); if sprite is empty or out of bounds, returns (None, None, None) instead
	"""

	# Sprite Y values are offset by 1 (https://www.nesdev.org/wiki/PPU_OAM#Byte_0)
	sprite_y = oam[0] + 1
	sprite_tile_idx = oam[1]
	sprite_flags = oam[2]
	sprite_x = oam[3]

	if sprite_y >= 240 or sprite_x >= 255:
		# Due to hardware bug, x=255 cannot hit (this is checked again later for sprites near 255, but if sprite is
		# definitely OOB then don't bother processing any further)
		logger.debug('Sprite zero hit: sprite zero is out of bounds, no hit')
		return None, None, None

	if ppuctrl & 0b0010_0000:
		sprite_tile = chr_tiles_8x16[sprite_tile_idx]
	else:
		sprite_tile_idx_offset_8x8 = 256 if (ppuctrl & 0b0000_1000) else 0
		sprite_tile = chr_tiles_8x8[sprite_tile_idx + sprite_tile_idx_offset_8x8]

	# If sprite is empty, don't bother with any of the other steps
	# TODO optimization: precalculate all tiles that are empty
	if not sprite_tile.any():
		logger.debug('Sprite zero hit: sprite zero is empty, no hit')
		return None, None, None

	if sprite_flags & 0b1000_0000:
		sprite_tile = np.flipud(sprite_tile)

	if sprite_flags & 0b0100_0000:
		sprite_tile = np.fliplr(sprite_tile)

	return sprite_tile, sprite_x, sprite_y


def _sprite_zero_hit_render_background_region(
		*,
		ppuctrl: uint8,
		vram: bytes | bytearray,
		vertical_mirroring: bool,
		chr_tiles_8x8: np.ndarray,
		first_tile_x: int,
		first_tile_y: int,
		) -> np.ndarray:

	sprites_8x16 = bool(ppuctrl & 0b0010_0000)
	bg_pattern_table_select = bool(ppuctrl & 0b0001_0000)

	nametable_a = np.frombuffer(vram[ : 960], dtype=np.uint8).reshape((30, 32))
	nametable_b = np.frombuffer(vram[ 0x400 : 0x400 + 960 ], dtype=np.uint8).reshape((30, 32))

	bg_region = np.zeros((24 if sprites_8x16 else 16, 16), dtype=np.bool)

	# TODO optimization: if sprite_x_within_region or sprite_y_within_region is 0, can iterate 1 less in that dimension
	for y in range(3 if sprites_8x16 else 2):
		tile_y = first_tile_y + y
		for x in range(2):
			tile_x = first_tile_x + x

			if vertical_mirroring:
				pick_b = bool(ppuctrl & 0b0000_0010)
				if tile_y >= 30:
					pick_b = not pick_b
			else:
				pick_b = bool(ppuctrl & 0b0000_0001)
				if tile_x >= 32:
					pick_b = not pick_b

			nametable_tile_y = tile_y % 30
			nametable_tile_x = tile_x % 32
			nametable = nametable_b if pick_b else nametable_a

			bg_tile_idx = int(nametable[nametable_tile_y, nametable_tile_x])

			if bg_pattern_table_select:
				bg_tile_idx += 256

			bg_tile = chr_tiles_8x8[bg_tile_idx]
			bg_region[8*y : 8*y + 8, 8*x : 8*x + 8] = bg_tile

	return bg_region


def _unraveled_argmax(arr: np.ndarray):
	# Array is probably already in C-order, but explicitly ravel it to be sure
	idx = np.argmax(arr.ravel(order='C'))
	return np.unravel_index(idx, arr.shape)


def _sprite_zero_hit_find_hit(
		*,
		ppumask: uint8,
		sprite_tile: np.ndarray,
		bg_region: np.ndarray,
		sprite_x: int,
		sprite_x_within_region: int,
		sprite_y_within_region: int,
		sprite_zero_debug_im: np.ndarray | None,
		) -> tuple[int, int] | tuple[None, None]:

	# Calculate background-sprite overlap

	sprite_tile_overlap = np.logical_and(
		sprite_tile,
		bg_region[
			sprite_y_within_region : sprite_y_within_region + sprite_tile.shape[0],
			sprite_x_within_region : sprite_x_within_region + 8]
	)

	# Handle PPUMASK option to hide left 8 pixels

	if (ppumask & 0b0000_0110) != 0b0000_0110:
		region_start_screen_x = sprite_x - sprite_x_within_region
		ignore_columns = 8 - region_start_screen_x
		if ignore_columns > 0:
			sprite_tile_overlap[:, :ignore_columns] = False
			if sprite_zero_debug_im is not None:
				sprite_zero_debug_im[:, :ignore_columns, :] //= 2

	# Find first non-False pixel (if any)

	y_within_sprite_tile, x_within_sprite_tile = _unraveled_argmax(sprite_tile_overlap)

	assert 0 <= y_within_sprite_tile < sprite_tile.shape[0] and 0 <= x_within_sprite_tile < 8

	if not sprite_tile_overlap[y_within_sprite_tile, x_within_sprite_tile]:
		return None, None

	return y_within_sprite_tile, x_within_sprite_tile


class Ppu:
	def __init__(
			self,
			rom_chr: bytes,
			rom_header: INesHeader,
			):

		self.rom_chr: Final[bytes] = rom_chr

		self._chr_tiles_8x8_mask = chr_to_stacked(self.rom_chr) > 0
		self._chr_tiles_8x16_mask = chr_to_stacked(self.rom_chr, tall=True) > 0

		self._vertical_mirroring = rom_header.vertical_mirroring

		self.nametable_layout: Final[tuple[int, int, int, int]] = (
			NAMETABLE_LAYOUT_VERTICAL if self._vertical_mirroring else NAMETABLE_LAYOUT_HORIZONTAL
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

		self.vblank: bool = False
		self.nmi: bool = False

		self.sprite_zero_hit_loc: tuple[int, int] = SPRITE_ZERO_HIT_NONE

		self.odd_frame: bool = False

		self.vblank_start_callback: Callable[[], None] | None = None
		self.vblank_end_callback: Callable[[], None] | None = None

		self.debug_status_im = np.zeros((TOTAL_ROWS, 3), dtype=np.uint8)
		self.sprite_zero_debug_im = np.zeros((24, 16, 3), dtype=np.uint8)

	@property
	def vblank_nmi_enable(self) -> bool:
		return bool(self.ppuctrl & 0b1000_0000)

	@property
	def sprites_8x16(self) -> bool:
		return bool(self.ppuctrl & 0b0010_0000)

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
		# TODO: this is in a hot path, optimize it better (can finish multiple rows at once)
		self.col += cycles
		while self.col >= COLUMNS:
			self.col -= COLUMNS
			self._finish_row()

	def _finish_row(self) -> None:

		# Optimization: this is in a hot path, so cache this for the sake of fewer self.__getattr__()
		row_num = self.row

		assert row_num < TOTAL_ROWS

		if row_num < 240:
			# TODO accuracy: fire this as soon as we hit the relevant pixel, not at the end of the row
			if row_num == self.sprite_zero_hit_loc[0]:
				logger.debug(f'Sprite zero hit on row {row_num}')
				self.ppustatus |= 0b0100_0000
				self.debug_status_im[row_num, 1] = 255

		elif row_num == VBLANK_START_ROW:
			# TODO accuracy: technically this occurs 1 PPU clock later
			self._vblank_start()

		elif row_num == VBLANK_END_ROW:
			# TODO accuracy: technically this occurs 1 PPU clock later
			self._vblank_end()

		self.row = row_num = (row_num + 1) % TOTAL_ROWS

		if row_num == 0:
			self.frame_count += 1
			if self.odd_frame:
				self.col += 1
			self.odd_frame = not self.odd_frame

	def _calculate_sprite_zero_hit(self) -> tuple[int, int]:
		"""
		Calculate pixel where sprite zero hit flag should get set, based on current data
		:returns: (y, x); if sprite zero never gets hit, then returns out of bounds coordinate (SPRITE_ZERO_HIT_NONE)
		"""

		self.sprite_zero_debug_im.fill(0)

		# If sprite or BG rendering is disabled, we do not hit
		if (self.ppumask & 0b0001_1000) != 0b0001_1000:
			logger.debug('Sprite zero hit: Rendering disabled, no hit')
			return SPRITE_ZERO_HIT_NONE

		# Load sprite

		sprite_tile, sprite_x, sprite_y = _sprite_zero_hit_load_sprite(
			ppuctrl=self.ppuctrl,
			oam=self.oam,
			chr_tiles_8x8=self._chr_tiles_8x8_mask,
			chr_tiles_8x16=self._chr_tiles_8x16_mask,
		)
		if sprite_tile is None:
			return SPRITE_ZERO_HIT_NONE

		# Load background tiles around this area

		bg_first_tile_x = (self.scroll_x + sprite_x) // 8
		bg_first_tile_y = (self.scroll_y + sprite_y) // 8

		bg_region = _sprite_zero_hit_render_background_region(
			ppuctrl=self.ppuctrl,
			vram=self.vram,
			vertical_mirroring=self._vertical_mirroring,
			chr_tiles_8x8=self._chr_tiles_8x8_mask,
			first_tile_x=bg_first_tile_x,
			first_tile_y=bg_first_tile_y,
		)

		if not bg_region.any():
			logging.debug('Sprite zero hit: background region is empty, no hit')
			return SPRITE_ZERO_HIT_NONE

		self.sprite_zero_debug_im[:bg_region.shape[0], :, 2] = np.where(bg_region, 255, 0)

		# Align sprite relative to BG tiles

		sprite_x_within_region = self.scroll_x + sprite_x - (8 * bg_first_tile_x)
		sprite_y_within_region = self.scroll_y + sprite_y - (8 * bg_first_tile_y)
		assert 0 <= sprite_x_within_region < 8
		assert 0 <= sprite_y_within_region < 8

		self.sprite_zero_debug_im[
			sprite_y_within_region : sprite_y_within_region + sprite_tile.shape[0],
			sprite_x_within_region : sprite_x_within_region + 8,
			0] = np.where(sprite_tile, 255, 0)

		# Find hit

		y_within_sprite_tile, x_within_sprite_tile = _sprite_zero_hit_find_hit(
			ppumask=self.ppumask,
			sprite_tile=sprite_tile,
			bg_region=bg_region,
			sprite_x=sprite_x,
			sprite_x_within_region=sprite_x_within_region,
			sprite_y_within_region=sprite_y_within_region,
			sprite_zero_debug_im=self.sprite_zero_debug_im
		)

		if y_within_sprite_tile is None:
			logging.debug(f'Sprite zero hit: sprite at ({sprite_x}, {sprite_y}) does not hit')
			return SPRITE_ZERO_HIT_NONE

		# Set this pixel to green
		self.sprite_zero_debug_im[
			sprite_y_within_region + y_within_sprite_tile,
			sprite_x_within_region + x_within_sprite_tile,
			...] = (0, 255, 0)

		# Adjust coordinates to be relative to screen, and check bounds

		screen_x = sprite_x + x_within_sprite_tile
		screen_y = sprite_y + y_within_sprite_tile

		if screen_x >= 256 or screen_y >= 240:
			logger.debug(f'Sprite zero hit: just out of bounds: ({screen_x}, {screen_y}) (part of tile was in bounds), no hit')
			return SPRITE_ZERO_HIT_NONE

		if screen_x == 255:
			logger.info(f'Sprite zero hit: hit at (255, {screen_y}), which does not trigger hit (emulating hardware bug)')
			return SPRITE_ZERO_HIT_NONE

		logger.debug(
			f'Sprite zero hit: hit at ({screen_x}, {screen_y}); '
			f'within tile: ({x_within_sprite_tile}, {y_within_sprite_tile})'
		)
		return screen_y, screen_x

	def tick_until_ppustatus_change(self) -> None:
		"""
		Tick clock until next PPUSTATUS change and/or start or end of VBLANK

		Although CPU doesn't need to care about VBLANK changes that don't change PPUSTATUS (i.e. end after flag has been
		cleared, or start in rare hardware corner case), the main outer emulator loop needs at least 1 CPU tick to
		happen after start and after end of VBLANK
		"""

		logger.debug('Waiting for next PPUSTATUS or VBLANK change')

		ppustatus_was = self.ppustatus
		vblank_was = self.vblank
		row_start = self.row

		# Tick ahead to end of this line
		# This also prevents self._col from overflowing on an odd frame
		columns_remaining = COLUMNS - self.col
		assert columns_remaining >= 0
		self._tick_clock(columns_remaining)
		assert self.col <= 1  # Usually 0, but can be 1 on row 0 due to odd frame behavior
		assert self.row != row_start

		# TODO optimization: Calculate when the next PPUSTATUS change will happen and tick straight there instead of
		# 1 row at a time

		while self.vblank == vblank_was and self.ppustatus == ppustatus_was:
			# Tick ahead 1 row
			# Optimization: skip going through self._tick_clock(COLUMNS) or incrementing self._col
			self._finish_row()
			# Note that _finish_row() can increment self.col by 1 on odd frame, but overflow should not be possible here
			# due to _tick_clock(columns_remaining) aboive
			assert self.col <= 1

		row_end = self.row

		if row_end == row_start:
			# Slept an entire frame (except for a few columns) - this often happens right on startup
			self.debug_status_im[:, 2] = 255
		elif row_end > row_start:
			self.debug_status_im[row_start:row_end, 2] = 255
		else:
			self.debug_status_im[row_start:, 2] = 255
			self.debug_status_im[:row_end, 2] = 255

	def _vblank_start(self):
		# Set vblank
		self.ppustatus |= 0b1000_0000
		self.vblank = True
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
		self.vblank = False
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
				ret = self.ppustatus
				# Reading PPUSTATUS clears vblank bit
				self.ppustatus &= 0b0111_1111
				self.write_latch = False
				return ret
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
			# TODO optimization: Some PPU writes do not affect Sprite Zero Hit and do not need to update this
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
