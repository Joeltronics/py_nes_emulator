#!/usr/bin/env python3

from pathlib import Path
from typing import Final

import numpy as np

from nes.rom import INesHeader
from nes.graphics_utils import chr_to_array, chr_to_stacked, grey_to_rgb, load_palette_file, upscale


# From https://www.nesdev.org/wiki/File:2C02G_wiki.pal
# TODO: use __file__ directory instead
NES_PALETTE: Final[np.ndarray] = load_palette_file(Path('nes') / '2C02G_wiki.pal')


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

		self._frame_rgb = np.zeros((240, 256, 3), dtype=np.uint8)

		self._chr_tiles = chr_to_stacked(self._rom_chr)

		self._chr_im_2bit = chr_to_array(self._rom_chr, width=16)
		self._chr_im_rgb = grey_to_rgb(LUT_2BIT_TO_8BIT[self._chr_im_2bit])

		# self._nametables_indexed = np.zeros((480, 512), dtype=np.uint8)
		self._nametables_rgb = np.zeros((480, 512, 3), dtype=np.uint8)

		# self._sprites_indexed = np.zeros((240, 256), dtype=np.uint8)
		self._sprites_rgb = np.zeros((240 + 7, 256 + 7, 3), dtype=np.uint8)
		self._sprite_mask = np.zeros((240 + 7, 256 + 7), dtype=np.bool)

		self._full_palette_im = np.arange(64, dtype=np.uint8).reshape((4, 16))
		self._full_palette_im = NES_PALETTE[self._full_palette_im]
		assert self._full_palette_im.shape == (4, 16, 3)

		self._palette_im = np.zeros((2, 16, 3), dtype=np.uint8)

		if save_chr:
			_save_chr(self._chr_im_rgb)

	def get_chr_as_rgb(self) -> np.ndarray:
		"""
		Returns CHR data, as uint8 RGB
		"""
		return self._chr_im_rgb

	def get_frame_rgb(self) -> np.ndarray:
		"""
		Returns rendered frame, as uint8 RGB
		"""
		return self._frame_rgb

	def get_nametables_rgb(self) -> np.ndarray:
		return self._nametables_rgb

	def get_sprites_rgb(self) -> np.ndarray:
		return self._sprites_rgb

	def get_sprites_mask(self) -> np.ndarray:
		return self._sprite_mask

	def get_current_palettes_im(self) -> np.ndarray:
		return self._palette_im

	def get_full_palette_im(self) -> np.ndarray:
		return self._full_palette_im

	def _mirror(self, a, b):
		if self._vertical_mirroring:
			row = np.hstack([a, b])
			return np.vstack([row, row])
		else:
			col = np.vstack([a, b])
			return np.hstack([col, col])

	def _render_nametables(self, *, ppuctrl, vram, palette_ram):

		if ppuctrl & 0b0000_0011:
			raise NotImplementedError('Base nametable address is not yet supported')

		nametable_a = vram[:0x400]
		nametable_b = vram[0x400:0x800]

		bg_pattern_table_select = bool(ppuctrl & 0b0001_0000)

		bg_color = palette_ram[0]
		palettes = np.array(palette_ram[:16], dtype=np.uint8).reshape((4, 4))
		# Ensure bg_color is used as first color of all palettes
		# TODO: This will probably need to be an alpha mask once supporting sprite priority
		palettes[:, 0] = bg_color

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

		nametable_a_indexed = _palettize_nametable(nametable_data=nametable_a, nametable_chr_2bit=nametable_a_2bit, palettes=palettes)
		nametable_b_indexed = _palettize_nametable(nametable_data=nametable_b, nametable_chr_2bit=nametable_b_2bit, palettes=palettes)

		# Apply mirroring
		# TODO optimization: it may be slightly faster to do this after applying NES palette

		nametables_indexed = self._mirror(nametable_a_indexed, nametable_b_indexed)

		# Apply NES palette (6-bit -> 8-bit RGB)

		self._nametables_rgb = NES_PALETTE[nametables_indexed]

	def _render_sprites(self, *, ppuctrl, oam, palette_ram):

		# TODO: sprite image that shows all sprites, even if they're invisible

		sprites_8x16 = bool(ppuctrl & 0b0010_0000)

		sprite_pattern_table_select = bool(ppuctrl & 0b0000_1000)
		tile_idx_offset = 256 if sprite_pattern_table_select else 0

		if sprites_8x16:
			raise NotImplementedError('8x16 sprites are not yet supported')

		assert len(palette_ram) == 32
		bg_color = palette_ram[0]
		palettes = np.array(palette_ram[16:], dtype=np.uint8).reshape((4, 4))

		# Ensure bg_color is used as first color of all palettes
		# TODO: this isn't necessary with _sprite_mask
		palettes[:, 0] = bg_color

		# This array will include sprites that are off-screen too, hence why shape isn't (240, 256)
		sprites_indexed = np.full((256 + 7, 256 + 7), fill_value=bg_color, dtype=np.uint8)

		self._sprite_mask = np.zeros((256 + 7, 256 + 7), dtype=np.bool)

		# TODO: debug image of all 64 current sprites

		assert len(oam) == 256
		for sprite_idx in reversed(range(64)):

			y, tile_idx, flags, x = oam[4*sprite_idx : 4*(sprite_idx + 1)]
			# Y is offset by 1, but this will be applied during compositing later

			tile_idx += tile_idx_offset

			flip_v = bool(flags & 0b1000_0000)
			flip_h = bool(flags & 0b0100_0000)
			priority = bool(flags & 0b0010_0000)  # TODO: support sprite priority
			palette_idx = flags & 0x03

			tile = self._chr_tiles[tile_idx]

			if flip_v:
				tile = np.flipud(tile)

			if flip_h:
				tile = np.fliplr(tile)

			palette = palettes[palette_idx, ...]
			tile_palettized = palette[tile]

			# TODO: will need to store a mask for compositing purposes (and likely a 2nd mask for priority)

			sprites_indexed[y : y + 8, x : x + 8] = tile_palettized

			# np.where(tile == 0, 255, sprites_indexed[y : y + 8, x : x + 8], out=sprites_indexed[y : y + 8, x : x + 8])

			# TODO: maybe instead, use value 255?
			tile_mask = (tile > 0)
			assert tile_mask.shape == (8, 8)
			self._sprite_mask[y : y + 8, x : x + 8] = tile_mask

		self._sprites_rgb = NES_PALETTE[sprites_indexed]

	def render_frame(self, ppu: 'Ppu'):

		# Read from PPU
		# TODO: make functions for this instead of just accessing members directly
		ppuctrl = ppu.ppuctrl
		vram = ppu.vram
		oam = ppu.oam
		palette_ram = ppu.palette_ram
		scroll_x = ppu.scroll_x
		scroll_y = ppu.scroll_y

		# Make palette image
		palette_ram_idxs = np.frombuffer(palette_ram, dtype=np.uint8).reshape((2, 16))
		self._palette_im = NES_PALETTE[palette_ram_idxs]
		assert self._palette_im.shape == (2, 16, 3)

		# TODO: maybe handle this here instead of in nametable/sprite functions?
		# bg_color = palette_ram[0]
		# bg_palettes = np.array(palette_ram[:16], dtype=np.uint8).reshape((4, 4))
		# sprite_palettes = np.array(palette_ram[16:], dtype=np.uint8).reshape((4, 4))
		# bg_palettes[:, 0] = bg_color
		# sprite_palettes[:, 0] = bg_color

		# TODO: attribute table palette images

		# Make nametable (background) images
		self._render_nametables(ppuctrl=ppuctrl, vram=vram, palette_ram=palette_ram)

		# Sprites
		self._render_sprites(ppuctrl=ppuctrl, oam=oam, palette_ram=palette_ram)

		# Composite

		# TODO optimization: handle everything in indexed color, then palettize once at end

		# Composite background & sprites into frame_indexed
		self._frame_rgb = np.where(
			self._sprite_mask[:240, :256, np.newaxis],
			self._sprites_rgb[:240, :256, ...],
			self._nametables_rgb[scroll_y : 240 + scroll_y, scroll_x : 256 + scroll_x, ...]
		)
