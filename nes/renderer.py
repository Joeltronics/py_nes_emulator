#!/usr/bin/env python3

from pathlib import Path
from typing import Final

import numpy as np

from nes.ppu import Ppu
from nes.rom import INesHeader
from nes.graphics_utils import chr_to_array, chr_to_stacked, grey_to_rgb, load_palette_file, draw_rectangle
from nes.types import uint8, pointer16

# From https://www.nesdev.org/wiki/File:2C02G_wiki.pal
NES_PALETTES: Final[np.ndarray] = load_palette_file(Path(__file__).parent / '2C02G_wiki.pal')
NES_PALETTE_MAIN: Final[np.ndarray] = NES_PALETTES[0]

LUT_2BIT_TO_8BIT: Final[np.ndarray] = np.array([0, 256//3, 512//3, 255], dtype=np.uint8)


def _save_chr(chr_array_rgb: np.ndarray, scale=2, filename='chr.png'):
	from PIL import Image

	print(f'Saving as {filename}')

	height, width = chr_array_rgb.shape[:2]
	im = Image.fromarray(chr_array_rgb)
	im = im.resize((scale * width, scale * height), resample=Image.NEAREST)
	im.save(filename)


def _mirror(a: np.ndarray, b: np.ndarray, ppuctrl: uint8, vertical: bool) -> np.ndarray:
	"""
	Take nametables A & B and copy them to 2x2 layout, according to mirroring mode and PPUCTRL base nametable bits
	"""

	if vertical:
		# TODO: is this right? test it
		order = [b, a] if ppuctrl & 0b0000_0001 else [a, b]
		row = np.hstack(order)
		return np.vstack([row, row])
	else:
		order = [b, a] if ppuctrl & 0b0000_0010 else [a, b]
		col = np.vstack(order)
		return np.hstack([col, col])


def _unapply_nametable_select(im: np.ndarray, ppuctrl: uint8, vertical_mirroring: bool) -> np.ndarray:
	"""
	Nametables are assembled the way the PPU reads them (scroll cannot wrap around, but equivalent behavior can be
	achieved using PPUCTRL base nametable bits to swap the nametable order). This function takes an assembled order, and
	un-applies the effect of PPUCTRL nametable select (meaning scroll effectively wraps around), which is a more
	intuitive order for displaying.
	"""

	if vertical_mirroring:
		# TODO: as in _mirror, test this
		if ppuctrl & 0b0000_0001:
			# Swap left & right
			a = im[:, :256, ...]
			b = im[:, 256:, ...]
			return np.hstack((b, a))
	else:
		if ppuctrl & 0b0000_0010:
			# Swap top & bottom
			a = im[:240, ...]
			b = im[240:, ...]
			return np.vstack((b, a))

	return im


def _populate_nametable_tiles(
		*,
		nametable_a: bytes | bytearray,
		nametable_b: bytes | bytearray,
		chr_tiles_8x8: np.ndarray,
		ppuctrl: uint8,
		nametable_a_out: np.ndarray | None = None,
		nametable_b_out: np.ndarray | None = None,
		) -> tuple[np.ndarray, np.ndarray]:

	# As an optimization, we have 1 function that populates both nametables
	# TODO: If this can be numpy-optimized, then change it to only populate 1 nametable at a time

	if nametable_a_out is None:
		nametable_a_out = np.zeros((240, 256), dtype=np.uint8)
	if nametable_b_out is None:
		nametable_b_out = np.zeros((240, 256), dtype=np.uint8)

	# Get tile indexes

	tile_idx_offset = 256 if (ppuctrl & 0b0001_0000) else 0
	nametable_a_tileidx = np.frombuffer(nametable_a[:960], dtype=np.uint8).reshape((240 // 8, 256 // 8)).astype(np.intp)
	nametable_b_tileidx = np.frombuffer(nametable_b[:960], dtype=np.uint8).reshape((240 // 8, 256 // 8)).astype(np.intp)

	# Copy tiles from CHR

	# TODO optimization: see if this can be numpy optimized
	# nametable_a_tiles = self._chr_tiles_8x8[nametable_a_tileidx]
	# nametable_b_tiles = self._chr_tiles_8x8[nametable_b_tileidx]
	# print(f'{nametable_a_tiles.shape=}')
	# exit(1)

	for y8 in range(240 // 8):
		y = y8 * 8
		for x8 in range(256 // 8):
			x = x8 * 8
			nametable_a_out[y : y + 8, x : x + 8] = chr_tiles_8x8[nametable_a_tileidx[y8, x8] + tile_idx_offset, ...]
			nametable_b_out[y : y + 8, x : x + 8] = chr_tiles_8x8[nametable_b_tileidx[y8, x8] + tile_idx_offset, ...]

	return nametable_a_out, nametable_b_out


def _palettize_nametable(
		nametable_data: bytes | bytearray,
		nametable_chr_2bit: np.ndarray,
		palettes: np.ndarray,
		*,
		out: np.ndarray | None = None,
		) -> np.ndarray:

	assert np.amax(nametable_chr_2bit) < 4

	# Each byte contains palettes for 4 16x16 metatiles (i.e. covers a 32x32 total area)
	# https://www.nesdev.org/wiki/PPU_attribute_tables
	attribute_table = nametable_data[0x3C0:]

	if out is None:
		out = np.zeros((240, 256), dtype=np.uint8)

	# TODO: see if this can be numpy optimized
	for y32 in range(240 // 32 + 1):
		last_row = (y32 >= 240 // 32)

		y = y32 * 32

		for x32 in range(256 // 32):
			x = x32 * 32

			palette_byte = attribute_table[x32 + (8 * y32)]

			# Top left & top right metatiles

			palette_idx_tl = (palette_byte & 0b0000_0011)
			palette_idx_tr = (palette_byte & 0b0000_1100) >> 2

			palette_tl = palettes[palette_idx_tl, :]
			palette_tr = palettes[palette_idx_tr, :]

			out[y : y + 16, x      : x + 16] = palette_tl[nametable_chr_2bit[y : y + 16, x      : x + 16]]
			out[y : y + 16, x + 16 : x + 32] = palette_tr[nametable_chr_2bit[y : y + 16, x + 16 : x + 32]]

			if last_row:
				continue

			# Bottom left & bottom right metatiles

			palette_idx_bl = (palette_byte & 0b0011_0000) >> 4
			palette_idx_br = (palette_byte & 0b1100_0000) >> 6

			palette_bl = palettes[palette_idx_bl, :]
			palette_br = palettes[palette_idx_br, :]

			out[y + 16 : y + 32, x      : x + 16] = palette_bl[nametable_chr_2bit[y + 16 : y + 32, x      : x + 16]]
			out[y + 16 : y + 32, x + 16 : x + 32] = palette_br[nametable_chr_2bit[y + 16 : y + 32, x + 16 : x + 32]]

	return out


def _palettize_frame(frame_indexed: np.ndarray, ppumask: uint8) -> np.ndarray:
	"""
	:note: frame_indexed may be modified in-place
	"""
	greyscale = bool(ppumask & 0b0000_0001)
	if greyscale:
		# https://www.nesdev.org/wiki/PPU_registers#Color_control
		frame_indexed &= 0x30

	emphasis = (ppumask & 0b1110_0000) >> 5
	assert 0 <= emphasis < 8, f'{emphasis=}'
	palette = NES_PALETTES[emphasis]

	return palette[frame_indexed]


class Renderer:
	def __init__(
			self,
			rom_chr: bytes,
			rom_header: INesHeader,
			ppu: Ppu,
			*,
			save_chr: bool = False,
			):

		self._ppu = ppu

		self._rom_chr = rom_chr
		self._vertical_mirroring = rom_header.vertical_mirroring

		self._frame_indexed = np.zeros((240, 256), dtype=np.uint8)
		self._frame_im = np.zeros((240, 256, 3), dtype=np.uint8)

		self._chr_tiles_8x8 = chr_to_stacked(self._rom_chr)
		self._chr_tiles_8x16 = chr_to_stacked(self._rom_chr, tall=True)

		# TODO: for 8x16 games, it could be better to display CHR in the equivalent order
		self._chr_im_2bit = chr_to_array(self._rom_chr, width=16)
		self._chr_im = grey_to_rgb(LUT_2BIT_TO_8BIT[self._chr_im_2bit])

		self._nametable_a_2bit = np.zeros((240, 256), dtype=np.uint8)
		self._nametable_b_2bit = np.zeros((240, 256), dtype=np.uint8)
		self._nametable_a_indexed = np.zeros((240, 256), dtype=np.uint8)
		self._nametable_b_indexed = np.zeros((240, 256), dtype=np.uint8)
		self._nametables_indexed = np.full((480, 512), fill_value=255, dtype=np.uint8)
		self._nametable_debug_im = np.zeros((480, 512, 3), dtype=np.uint8)

		# These arrays will include sprites that are off-screen too, hence why shape isn't (240, 256)
		# 2nd dimension is depth:
		#   0 = background
		#   1 = behind background
		#   -1 (255) = in front of background
		# TODO: Try type np.int8 instead
		self._sprite_layer_indexed = np.zeros((256 + 16, 256 + 7, 2), dtype=np.uint8)
		self._sprite_layer_debug_im = np.zeros((256 + 16, 256 + 7, 3), dtype=np.uint8)

		self._sprites_debug_indexed = np.zeros((64, 64), dtype=np.uint8)
		self._sprites_debug_im = np.zeros((64, 64, 3), dtype=np.uint8)

		self._full_palette_debug_im = np.arange(64, dtype=np.uint8).reshape((4, 16))
		self._full_palette_debug_im = NES_PALETTE_MAIN[self._full_palette_debug_im]
		assert self._full_palette_debug_im.shape == (4, 16, 3)

		self._current_palette_debug_im = np.zeros((2, 16, 3), dtype=np.uint8)

		self._ppu_debug_im = ppu.debug_status_im.reshape((ppu.debug_status_im.shape[0], 1, 3)).copy()
		self._sprite_zero_debug_im = ppu.sprite_zero_debug_im.copy()

		if save_chr:
			_save_chr(self._chr_im)

	def get_chr_im(self) -> np.ndarray:
		"""
		Returns CHR data, as uint8 RGB
		"""
		return self._chr_im

	def get_frame_im(self) -> np.ndarray:
		"""
		Returns rendered frame, as uint8 RGB
		"""
		return self._frame_im

	def get_nametables_debug_im(self) -> np.ndarray:
		return self._nametable_debug_im

	def get_sprites_debug_im(self) -> np.ndarray:
		return self._sprites_debug_im

	def get_sprite_layer_debug_im(self) -> np.ndarray:
		return self._sprite_layer_debug_im

	def get_current_palettes_debug_im(self) -> np.ndarray:
		return self._current_palette_debug_im

	def get_full_palette_debug_im(self) -> np.ndarray:
		return self._full_palette_debug_im

	def get_ppu_debug_im(self) -> np.ndarray:
		return self._ppu_debug_im

	def get_sprite_zero_debug_im(self) -> np.ndarray:
		return self._sprite_zero_debug_im

	def _render_nametables(self, *, bg_palettes: np.ndarray, bg_color: int) -> None:

		vram = self._ppu.vram
		ppuctrl = self._ppu.ppuctrl

		nametable_a = vram[:0x400]
		nametable_b = vram[0x400:0x800]

		# Populate nametable tiles (2-bit out)
		_populate_nametable_tiles(
			nametable_a=nametable_a,
			nametable_b=nametable_b,
			nametable_a_out=self._nametable_a_2bit,
			nametable_b_out=self._nametable_b_2bit,
			chr_tiles_8x8=self._chr_tiles_8x8,
			ppuctrl=ppuctrl,
		)

		# Apply palettes (2-bit -> 6-bit)
		_palettize_nametable(
			nametable_data=nametable_a, nametable_chr_2bit=self._nametable_a_2bit, palettes=bg_palettes,
			out=self._nametable_a_indexed)
		_palettize_nametable(
			nametable_data=nametable_b, nametable_chr_2bit=self._nametable_b_2bit, palettes=bg_palettes,
			out=self._nametable_b_indexed)

		# TODO: attribute table debug palette image

		# Apply mirroring
		self._nametables_indexed = _mirror(
			a=self._nametable_a_indexed, b=self._nametable_b_indexed, ppuctrl=ppuctrl, vertical=self._vertical_mirroring)

		self._make_nametable_debug_image(bg_color)

	def _make_nametable_debug_image(self, bg_color: uint8):

		ppu = self._ppu

		nametables_with_bg = self._nametables_indexed.copy()
		nametables_with_bg[nametables_with_bg == 255] = bg_color
		self._nametable_debug_im = NES_PALETTE_MAIN[nametables_with_bg]

		# Draw scroll area on debug nametable image
		draw_rectangle(self._nametable_debug_im, (255, 0, 255), ppu.scroll_x, ppu.scroll_y, 256, 240, wrap=True)

		# Un-apply nametable select in debug nametable image
		self._nametable_debug_im = _unapply_nametable_select(
			self._nametable_debug_im, ppuctrl=ppu.ppuctrl, vertical_mirroring=self._vertical_mirroring)

	def _render_sprites(
			self,
			*,
			sprite_palettes: np.ndarray,
			start_row: int,
			end_row: int,
			render_offscreen_sprites: bool = False,
			) -> None:

		first_segment = (start_row <= 0)

		oam = self._ppu.oam
		ppuctrl = self._ppu.ppuctrl

		sprites_8x16 = bool(ppuctrl & 0b0010_0000)
		h = 16 if sprites_8x16 else 8

		sprite_pattern_table_select = bool(ppuctrl & 0b0000_1000)
		tile_idx_offset_8x8 = 256 if sprite_pattern_table_select else 0

		sprites_indexed = self._sprite_layer_indexed
		sprites_debug_indexed = self._sprites_debug_indexed

		if first_segment:
			sprites_indexed.fill(0)
			sprites_debug_indexed.fill(0)

		outline_mask = np.zeros((256 + 16, 256 + 7), dtype=np.bool)

		assert len(oam) == 256
		for sprite_idx in reversed(range(64)):

			y, tile_idx, flags, x = oam[4*sprite_idx : 4*(sprite_idx + 1)]

			# Sprite Y values are offset by 1 (https://www.nesdev.org/wiki/PPU_OAM#Byte_0)
			# Technically it might be more accurate to apply this during compositing later, but this is a lot simpler
			y += 1

			if (not render_offscreen_sprites) and not (start_row - h <= y < end_row):
				continue

			flip_v = flags & 0b1000_0000
			flip_h = flags & 0b0100_0000
			depth = 1 if (flags & 0b0010_0000) else 255
			palette_idx = flags & 0x03

			if sprites_8x16:
				tile = self._chr_tiles_8x16[tile_idx]
			else:
				tile = self._chr_tiles_8x8[tile_idx + tile_idx_offset_8x8]

			if flip_v:
				tile = np.flipud(tile)

			if flip_h:
				tile = np.fliplr(tile)

			tile_palettized = sprite_palettes[palette_idx, ...][tile]
			tile_mask = tile > 0
			sprites_indexed[y : y + h, x : x + 8, 0][tile_mask] = tile_palettized[tile_mask]
			sprites_indexed[y : y + h, x : x + 8, 1][tile_mask] = depth

			# TODO: different color depending on sprite flags, a bit like for sprite 0
			# (need to make outline_mask RGB instead of bool)
			draw_rectangle(outline_mask, True, x, y, 8, h)

			ys, xs = divmod(sprite_idx, 8)
			xs *= 8
			ys *= 8
			# If 8x16, will only put top tile into _sprites_debug_im (TODO: both)
			sprites_debug_indexed[ys : ys + 8, xs : xs + 8] = tile_palettized[:8, ...]

		sprites_debug_indexed[sprites_debug_indexed >= 64] = 0
		self._sprites_debug_im = NES_PALETTE_MAIN[sprites_debug_indexed]

		sprites_im = sprites_indexed[..., 0].copy()
		sprite_im_bg = sprites_indexed[..., 1] == 0
		sprites_im[sprite_im_bg] = 0x0F
		sprites_im[:240, :256][sprite_im_bg[:240, :256]] = 0
		sprites_im = NES_PALETTE_MAIN[sprites_im]

		sprites_im[np.logical_and(outline_mask, sprite_im_bg), ...] = (255, 0, 255)

		# Special outline for sprite 0
		draw_rectangle(sprites_im, (0, 255, 0), oam[3], oam[0] + 1, 8, 16 if sprites_8x16 else 8)

		self._sprite_layer_debug_im = sprites_im

	def _load_palettes(self) -> np.ndarray:

		palettes = np.frombuffer(self._ppu.palette_ram, dtype=np.uint8).reshape((8, 4)).copy()
		bg_color = palettes[0, 0]
		for idx in range(4):
			palettes[4 + idx, 0] = palettes[idx, 0]

		# Make palette image before applying background colors
		palette_ram_idxs = palettes.reshape((2, 16))
		self._current_palette_debug_im = NES_PALETTE_MAIN[palette_ram_idxs]
		assert self._current_palette_debug_im.shape == (2, 16, 3)

		# Value 255 indicates a transparent pixel
		palettes[:, 0] = 255

		bg_palettes = palettes[:4, :]
		sprite_palettes = palettes[4:8, :]

		return bg_color, bg_palettes, sprite_palettes

	def _composite_layers(self, bg_color: int, start_row: int, end_row: int) -> None:

		first_segment = (start_row <= 0)

		scroll_x = self._ppu.scroll_x
		scroll_y = self._ppu.scroll_y

		ppumask = self._ppu.ppumask
		render_sprites =        bool(ppumask & 0b0001_0000)
		render_bg =             bool(ppumask & 0b0000_1000)
		sprites_left_8_pixels = bool(ppumask & 0b0000_0100)
		bg_left_8_pixels =      bool(ppumask & 0b0000_0010)

		nametables_onscreen = None
		if render_bg:
			nametables_onscreen = self._nametables_indexed[scroll_y : 240 + scroll_y, scroll_x : 256 + scroll_x]
			if not bg_left_8_pixels:
				nametables_onscreen[start_row:end_row, :8] = 255

		sprites_onscreen = None
		sprite_depth = None
		if render_sprites:
			sprites_onscreen = self._sprite_layer_indexed[:240, :256, 0]
			sprite_depth     = self._sprite_layer_indexed[:240, :256, 1]
			if not sprites_left_8_pixels:
				sprite_depth[start_row:end_row, :8] = 0

		assert (nametables_onscreen is None) or nametables_onscreen.shape == (240, 256)
		assert (sprites_onscreen is None) or sprites_onscreen.shape == (240, 256)
		assert (sprite_depth is None) or sprite_depth.shape == (240, 256)

		# Base layer: background color
		# Assume palette RAM won't get written during rendering (this is difficult/risky in real hardware, and isn't
		# currently implemented in PPU); that means we're fine to just fill entire frame once
		if first_segment:
			self._frame_indexed.fill(bg_color)

		# Background sprites
		if render_sprites:
			assert sprites_onscreen is not None
			sprites_bg_mask = (sprite_depth[start_row:end_row, ...] == 1)
			self._frame_indexed[start_row:end_row, ...][sprites_bg_mask] = \
				sprites_onscreen[start_row:end_row, ...][sprites_bg_mask]

		# Background nametables
		if render_bg:
			assert nametables_onscreen is not None
			nametable_nonbg_mask = (nametables_onscreen[start_row:end_row, ...] < 64)
			self._frame_indexed[start_row:end_row, ...][nametable_nonbg_mask] = \
				nametables_onscreen[start_row:end_row, ...][nametable_nonbg_mask]

		# Foreground sprites
		if render_sprites:
			assert sprites_onscreen is not None
			sprites_fg_mask = (sprite_depth[start_row:end_row, ...] == 255)
			self._frame_indexed[start_row:end_row, ...][sprites_fg_mask] = \
				sprites_onscreen[start_row:end_row, ...][sprites_fg_mask]

	def render_frame(self, start_row: int, end_row: int):

		first_segment = (start_row <= 0)
		last_segment = (end_row >= 239)
		entire_frame = first_segment and last_segment

		# FIXME: for some reason this can flicker with split-screen rendering
		# e.g. in SMB, once we scroll past the first screen - something is wrong with base nametable getting set to 1
		# It seems it renders properly on maybe 75% of frames
		# PPUSCROLL gets updated twice on row 31, then PPUCTRL (base nametable address) gets updated on row 32
		# Could be a timing issue, or could be relating to not implementing PPU shared internal registers properly

		# TODO: right now this re-renders full screen, even if we're only rendering a small area

		# TODO: make PPU getter functions instead of accessing members directly (and make the members private)
		ppu = self._ppu

		# We could return early if PPUMASK rendering disabled, but then debug images would not get made

		# Load palettes
		bg_color, bg_palettes, sprite_palettes = self._load_palettes()

		# Make nametable (background) images
		self._render_nametables(bg_palettes=bg_palettes, bg_color=bg_color)
		# TODO: with split screen scroll, draw scroll area for just this region onto nametables

		# Sprites
		self._render_sprites(sprite_palettes=sprite_palettes, start_row=start_row, end_row=end_row)

		# Composite background & sprites into frame
		self._composite_layers(bg_color=bg_color, start_row=start_row, end_row=end_row)

		# Palettize
		self._frame_im[start_row:end_row, ...] = _palettize_frame(self._frame_indexed[start_row:end_row, ...], ppumask=ppu.ppumask)

		if last_segment:
			# Grab debug images from PPU
			self._ppu_debug_im = ppu.debug_status_im.reshape((ppu.debug_status_im.shape[0], 1, 3)).copy()
			self._sprite_zero_debug_im = ppu.sprite_zero_debug_im.copy()
			ppu.done_rendering()
