#!/usr/bin/env python3

import logging
from pathlib import Path

import pygame

import numpy as np


logger = logging.getLogger(__name__)


def grey_to_rgb(arr: np.ndarray) -> np.ndarray:
	assert arr.ndim == 2
	return np.dstack([arr, arr, arr])


def upscale(arr: np.ndarray, scale: int | tuple[int, int]) -> np.ndarray:
	"""
	Nearest-neighbour upscaling
	"""
	if isinstance(scale, int):
		scale = (scale, scale)
	return arr.repeat(scale[0], 0).repeat(scale[1], 1)


_upscale = upscale


def array_to_surface(arr: np.ndarray, upscale: int | tuple[int, int] = 1, into=None):
	if (not isinstance(upscale, int)) or (upscale > 1):
		arr = _upscale(arr, upscale)

	arr = arr.swapaxes(1,0)

	if into is None:
		return pygame.surfarray.make_surface(arr)
	else:
		pygame.pixelcopy.array_to_surface(into, arr)
		return into


def draw_rectangle(
		arr: np.ndarray,
		color,
		x: int, y: int, w: int, h: int,
		*,
		wrap=False,
		) -> None:

	assert w >= 0 and h >= 0, f'{w=}, {h=}'

	x1 = x
	y1 = y
	x2 = x + w - 1
	y2 = y + h - 1

	if wrap:
		arr_h, arr_w = arr.shape[:2]

		x1 %= arr_w
		x2 %= arr_w

		y1 %= arr_h
		y2 %= arr_h

		if x1 <= x2:
			arr[y1, x1:x2, ...] = color
			arr[y2, x1:x2, ...] = color
		else:
			arr[y1,   :x2, ...] = color
			arr[y1,   :x2, ...] = color
			arr[y2, x1:  , ...] = color
			arr[y2, x1:  , ...] = color

		if y1 <= y2:
			arr[y1:y2, x1, ...] = color
			arr[y1:y2, x2, ...] = color
		else:
			arr[  :y2, x1, ...] = color
			arr[  :y2, x2, ...] = color
			arr[y1:  , x1, ...] = color
			arr[y1:  , x2, ...] = color

	else:
		arr[y1      , x1 : x2 , ...] = color
		arr[     y2 , x1 : x2 , ...] = color
		arr[y1 : y2 , x1      , ...] = color
		arr[y1 : y2 ,      x2 , ...] = color


def chr_to_array(rom_chr: bytes, width=16) -> np.ndarray:
	"""
	:returns: CHR as array (2-bit), shape (512/width*8, width*8)
	"""

	height = 512 // width
	if (height * width) != 512:
		raise ValueError(f'width must be divisor of 512: {width}')

	# TODO: use numpy operations for this instead of 3 nested loops

	chr_arr = np.empty((8*height, 8*width), dtype=np.uint8)
	for tile_idx in range(512):

		tile_y, tile_x = divmod(tile_idx, width)
		tile_x *= 8
		tile_y *= 8

		for row in range(8):
			low_byte = rom_chr[16 * tile_idx + row]
			high_byte = rom_chr[16 * tile_idx + row + 8]
			for col in range(8):

				mask = (1 << (7 - col))

				low_bit = int(bool(low_byte & mask))
				high_bit = int(bool(high_byte & mask))
				pixel = low_bit + 2 * high_bit

				chr_arr[tile_y + row, tile_x + col] = pixel

	return chr_arr


def chr_to_stacked(rom_chr: bytes, tall=False) -> np.ndarray:
	"""
	:returns: CHR as array (2-bit), shape (256, 16, 8) if tall, otherwise (512, 8, 8)

	:note: if tall, order will be corrected for OAM bit order when in 8x16 mode, i.e. resulting array directly takes
	OAM byte 1 as index
	"""

	# TODO optimization: I suspect (512, 8, 8) is faster than (8, 8, 512), but confirm (try both and compare performance)
	tiles_8x8 = chr_to_array(rom_chr, width=1).reshape((512, 8, 8)).copy()

	if tall:
		# Could numpy optimize this, but it only happens on load, so not a high priority
		tiles_8x16 = np.empty((256, 16, 8), dtype=np.uint8)

		for idx_out in range(256):
			# In 8x16 mode, there's some bit shuffling needed to get tile index
			# https://www.nesdev.org/wiki/PPU_OAM#Byte_1
			# Do it once now rather than every time we render a sprite later
			low_bit = (idx_out & 1)
			high_bits = idx_out & 0b1111_1110
			idx_in = 256 * low_bit + high_bits

			tiles_8x16[idx_out, :8, :] = tiles_8x8[idx_in    , :, :]
			tiles_8x16[idx_out, 8:, :] = tiles_8x8[idx_in + 1, :, :]

		return tiles_8x16

	else:
		return tiles_8x8


def load_palette_file(path: Path | str) -> np.ndarray:
	data = Path(path).read_bytes()

	if len(data) < 192:
		raise ValueError(f'Invalid palette file - expected length >= 192, actual length {len(data)}')

	if len(data) >= 1536:

		if len(data) > 1536:
			logger.warning(f'Unexpected palette file length: {len(data)}, truncating to 1536')

		palettes = np.frombuffer(data[:1536], dtype=np.uint8).reshape((8, 64, 3))

	else:
		# TODO: Generate emphasis palettes (de-gamma, multiply by 0.816328, and re-gamma)
		# https://www.nesdev.org/wiki/NTSC_video#Color_Tint_Bits
		logger.warning('Palette file does not contain emphasis palettes, PPU emphasis will not be supported')

		if True:
			# Fast numpy code
			palette = np.frombuffer(data[:192], dtype=np.uint8).reshape((8, 64, 3))
		else:
			# Original slow iterative code
			palette = np.empty((64, 3), dtype=np.uint8)
			for idx in range(64):
				palette[idx, 0] = data[3 * idx]
				palette[idx, 1] = data[3 * idx + 1]
				palette[idx, 2] = data[3 * idx + 2]

		palettes = np.stack([palette] * 8, axis=0)
	
	assert palettes.shape == (8, 64, 3), f'{palettes.shape=}'

	return palettes
