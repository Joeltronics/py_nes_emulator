#!/usr/bin/env python3

from pathlib import Path
from typing import Final

import numpy as np

from nes.rom import INesHeader
from nes.graphics_utils import chr_to_array, chr_to_stacked, grey_to_rgb, load_palette_file, upscale, draw_rectangle
from nes.types import uint8, pointer16


# From https://www.nesdev.org/wiki/File:2C02G_wiki.pal
NES_PALETTE: Final[np.ndarray] = load_palette_file(Path(__file__).parent / '2C02G_wiki.pal')


LUT_2BIT_TO_8BIT: Final[np.ndarray] = np.array([0, 256//3, 512//3, 255], dtype=np.uint8)


def _save_chr(chr_array_rgb: np.ndarray, scale=2, filename='chr.png'):
	from PIL import Image

	print(f'Saving as {filename}')

	height, width = chr_array_rgb.shape[:2]
	im = Image.fromarray(chr_array_rgb)
	im = im.resize((scale * width, scale * height), resample=Image.NEAREST)
	im.save(filename)


def _palettize_nametable(
		nametable_data: bytes | bytearray,
		nametable_chr_2bit: np.ndarray,
		palettes: np.ndarray,
		) -> np.ndarray:

	assert np.amax(palettes) < 64
	assert np.amax(nametable_chr_2bit) < 4

	# Each byte contains palettes for 4 16x16 metatiles (i.e. covers a 32x32 total area)
	# https://www.nesdev.org/wiki/PPU_attribute_tables
	attribute_table = nametable_data[0x3C0:]

	# Initialize to 255 (max valid value is 63), so later we can tell if any pixels were missed
	nametable_indexed = np.full((240, 256), fill_value=255, dtype=np.uint8)

	# TODO: see if this can be numpy optimized
	for y32 in range(240 // 32 + 1):
		last_row = (y32 >= 240 // 32)

		y = y32 * 32

		for x32 in range(256 // 32):
			x = x32 * 32

			palette_byte = attribute_table[x32 + (8 * y32)]

			# Upper 2 tiles

			palette_idx_tl = (palette_byte & 0b0000_0011)
			palette_idx_tr = (palette_byte & 0b0000_1100) >> 2

			palette_tl = palettes[palette_idx_tl, :]
			palette_tr = palettes[palette_idx_tr, :]

			nametable_indexed[y : y + 16, x      : x + 16] = palette_tl[nametable_chr_2bit[y : y + 16, x      : x + 16]]
			nametable_indexed[y : y + 16, x + 16 : x + 32] = palette_tr[nametable_chr_2bit[y : y + 16, x + 16 : x + 32]]

			if not last_row:
				# Lower 2 tiles

				palette_idx_bl = (palette_byte & 0b0011_0000) >> 4
				palette_idx_br = (palette_byte & 0b1100_0000) >> 6

				palette_bl = palettes[palette_idx_bl, :]
				palette_br = palettes[palette_idx_br, :]

				nametable_indexed[y + 16 : y + 32, x      : x + 16] = palette_bl[nametable_chr_2bit[y + 16 : y + 32, x      : x + 16]]
				nametable_indexed[y + 16 : y + 32, x + 16 : x + 32] = palette_br[nametable_chr_2bit[y + 16 : y + 32, x + 16 : x + 32]]

	assert np.amax(nametable_indexed) < 64  # Ensure all pixels were touched (any missed pixels will still be 255)

	return nametable_indexed


class Renderer:
	def __init__(
			self,
			rom_chr: bytes,
			rom_header: INesHeader,
			*,
			save_chr: bool = False,
			):

		self._rom_chr = rom_chr
		self._vertical_mirroring = rom_header.vertical_mirroring

		self._frame_im = np.zeros((240, 256, 3), dtype=np.uint8)

		self._chr_tiles = chr_to_stacked(self._rom_chr)

		self._chr_im_2bit = chr_to_array(self._rom_chr, width=16)
		self._chr_im = grey_to_rgb(LUT_2BIT_TO_8BIT[self._chr_im_2bit])

		self._nametables_indexed = np.zeros((480, 512), dtype=np.uint8)
		self._nametable_debug_im = np.zeros((480, 512, 3), dtype=np.uint8)

		self._sprite_layer_indexed = np.zeros((240 + 7, 256 + 7), dtype=np.uint8)
		self._sprite_layer_debug_im = np.zeros((240 + 7, 256 + 7, 3), dtype=np.uint8)

		self._sprites_debug_im = np.zeros((64, 64, 3), dtype=np.uint8)

		self._full_palette_debug_im = np.arange(64, dtype=np.uint8).reshape((4, 16))
		self._full_palette_debug_im = NES_PALETTE[self._full_palette_debug_im]
		assert self._full_palette_debug_im.shape == (4, 16, 3)

		self._current_palette_debug_im = np.zeros((2, 16, 3), dtype=np.uint8)

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

	def _mirror(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
		if self._vertical_mirroring:
			row = np.hstack([a, b])
			return np.vstack([row, row])
		else:
			col = np.vstack([a, b])
			return np.hstack([col, col])

	def _render_nametables(self, *, ppuctrl: uint8, vram: bytes | bytearray, bg_palettes: np.ndarray) -> None:

		if ppuctrl & 0b0000_0011:
			raise NotImplementedError('Base nametable address is not yet supported')

		nametable_a = vram[:0x400]
		nametable_b = vram[0x400:0x800]

		bg_pattern_table_select = bool(ppuctrl & 0b0001_0000)

		# Get tile indexes

		if True:
			# Fast numpy code
			nametable_a_tileidx = np.frombuffer(nametable_a[:960], dtype=np.uint8).reshape((240 // 8, 256 // 8)).astype(np.intp)
			nametable_b_tileidx = np.frombuffer(nametable_b[:960], dtype=np.uint8).reshape((240 // 8, 256 // 8)).astype(np.intp)
		else:
			# Slow iterative code
			nametable_a_tileidx = np.empty((240 // 8, 256 // 8), dtype=np.intp)
			nametable_b_tileidx = np.empty((240 // 8, 256 // 8), dtype=np.intp)
			for y in range(240 // 8):
				for x in range(256 // 8):
					addr = (256 // 8) * y + x
					nametable_a_tileidx[y, x] = nametable_a[addr]
					nametable_b_tileidx[y, x] = nametable_b[addr]

		if bg_pattern_table_select:
			nametable_a_tileidx += 256
			nametable_b_tileidx += 256

		# Copy tiles from CHR

		# TODO: see if this can be numpy optimized

		nametable_a_2bit = np.empty((240, 256), dtype=np.uint8)
		nametable_b_2bit = np.empty((240, 256), dtype=np.uint8)
		tiles = self._chr_tiles  # Optimization: avoid self.__getattr__() inside loop
		for y8 in range(240 // 8):
			y = y8 * 8
			for x8 in range(256 // 8):
				x = x8 * 8
				nametable_a_2bit[y : y + 8, x : x + 8] = tiles[nametable_a_tileidx[y8, x8], ...]
				nametable_b_2bit[y : y + 8, x : x + 8] = tiles[nametable_b_tileidx[y8, x8], ...]

		# Apply palettes (2-bit -> 6-bit)
		nametable_a_indexed = _palettize_nametable(nametable_data=nametable_a, nametable_chr_2bit=nametable_a_2bit, palettes=bg_palettes)
		nametable_b_indexed = _palettize_nametable(nametable_data=nametable_b, nametable_chr_2bit=nametable_b_2bit, palettes=bg_palettes)

		# TODO: attribute table debug palette image for debugging

		# Apply mirroring
		nametables_indexed = self._mirror(nametable_a_indexed, nametable_b_indexed)
		self._nametables_indexed = nametables_indexed

		# Palettize
		self._nametable_debug_im = NES_PALETTE[self._nametables_indexed]

	def _render_sprites(
			self,
			*,
			ppuctrl: uint8,
			oam: bytes | bytearray,
			sprite_palettes: np.ndarray,
			render_offscreen_sprites: bool = True,  # TODO: set this False, for optimization purposes
			) -> None:

		sprites_8x16 = bool(ppuctrl & 0b0010_0000)

		sprite_pattern_table_select = bool(ppuctrl & 0b0000_1000)
		tile_idx_offset = 256 if sprite_pattern_table_select else 0

		if sprites_8x16:
			raise NotImplementedError('8x16 sprites are not yet supported')

		# These arrays will include sprites that are off-screen too, hence why shape isn't (240, 256)
		# Value 255 indicates a transparent pixel
		sprites_indexed = np.full((256 + 8, 256 + 7), fill_value=255, dtype=np.uint8)

		sprites_debug_indexed = np.zeros((64, 64), dtype=np.uint8)

		outline_mask = np.zeros_like(sprites_indexed, dtype=np.bool)

		assert len(oam) == 256
		for sprite_idx in reversed(range(64)):

			y, tile_idx, flags, x = oam[4*sprite_idx : 4*(sprite_idx + 1)]

			# Y is offset by 1
			# Technically it might be more accurate to apply this during compositing later, but this is a lot simpler
			y += 1

			if y >= 240 and not render_offscreen_sprites:
				continue

			tile_idx += tile_idx_offset

			flip_v = bool(flags & 0b1000_0000)
			flip_h = bool(flags & 0b0100_0000)
			priority = bool(flags & 0b0010_0000)  # TODO: support sprite background priority (store a mask for it)
			palette_idx = flags & 0x03

			tile = self._chr_tiles[tile_idx]

			if flip_v:
				tile = np.flipud(tile)

			if flip_h:
				tile = np.fliplr(tile)

			tile_palettized = sprite_palettes[palette_idx, ...][tile]

			tile_mask = tile > 0
			sprites_indexed[y : y + 8, x : x + 8][tile_mask] = tile_palettized[tile_mask]

			# TODO: different color depending on sprite flags, and also for sprite 0
			# (need to make outline_mask RGB instead of bool)
			draw_rectangle(outline_mask, True, x, y, 8, 8)

			ys, xs = divmod(sprite_idx, 8)
			xs *= 8
			ys *= 8
			sprites_debug_indexed[ys : ys + 8, xs : xs + 8] = tile_palettized

		self._sprite_layer_indexed = sprites_indexed

		sprites_debug_indexed[sprites_debug_indexed >= 64] = 0
		self._sprites_debug_im = NES_PALETTE[sprites_debug_indexed]

		sprites_im = sprites_indexed.copy()
		sprite_im_bg = sprites_im >= 64
		sprites_im[sprite_im_bg] = 0
		sprites_im = NES_PALETTE[sprites_im]
		sprites_im[240, :, ...] = (255, 0, 255)

		sprites_im[np.logical_and(outline_mask, sprite_im_bg), ...] = (255, 0, 255)

		self._sprite_layer_debug_im = sprites_im

	def render_frame(self, ppu: 'Ppu'):

		# Read from PPU
		# TODO: make functions for this instead of accessing ppu members directly (and make the members private)
		ppuctrl = ppu.ppuctrl
		ppumask = ppu.ppumask  # TODO: use PPUMASK
		vram = ppu.vram
		oam = ppu.oam
		palette_ram = ppu.palette_ram
		scroll_x = ppu.scroll_x
		scroll_y = ppu.scroll_y

		# Palettes

		palettes = np.frombuffer(palette_ram, dtype=np.uint8).reshape((8, 4)).copy()
		# Make palette image before applying background color
		palette_ram_idxs = palettes.copy().reshape((2, 16))
		self._current_palette_debug_im = NES_PALETTE[palette_ram_idxs]
		assert self._current_palette_debug_im.shape == (2, 16, 3)
		# TODO: indicate unused palette entries, if they differ from background (draw an X on them?)
		bg_palettes = palettes[:4, :]
		sprite_palettes = palettes[4:8, :]
		# Value 255 indicates a transparent pixel
		# TODO: may want to use 255 for bg_palettes too once handling sprite priority
		# (treat this as 4 layers: bgcolor, bg sprites, nametable, fg sprites)
		bg_palettes[:, 0] = palettes[0, 0]
		sprite_palettes[:, 0] = 255

		# Make nametable (background) images
		self._render_nametables(ppuctrl=ppuctrl, vram=vram, bg_palettes=bg_palettes)

		# Draw scroll area on debug nametable image
		draw_rectangle(self._nametable_debug_im, (255, 0, 255), scroll_x, scroll_y, 256, 240)

		# Sprites
		self._render_sprites(ppuctrl=ppuctrl, oam=oam, sprite_palettes=sprite_palettes)

		# Composite background & sprites into frame

		nametables_onscreen = self._nametables_indexed[scroll_y : 240 + scroll_y, scroll_x : 256 + scroll_x]
		sprites_onscreen = self._sprite_layer_indexed[:240, :256]
		frame_indexed = np.where(
			sprites_onscreen < 64,
			sprites_onscreen,
			nametables_onscreen,
		)

		# Apply NES palette (6-bit -> 8-bit RGB)
		self._frame_im = NES_PALETTE[frame_indexed]
