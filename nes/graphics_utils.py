#!/usr/bin/env python3

from pathlib import Path

import pygame

import numpy as np


def grey_to_rgb(arr: np.ndarray) -> np.ndarray:
	assert arr.ndim == 2
	return np.dstack([arr, arr, arr])


def upscale(arr: np.ndarray, scale: int) -> np.ndarray:
	"""
	Nearest-neighbour upscaling
	"""
	return arr.repeat(scale, 0).repeat(scale, 1)


_upscale = upscale


def array_to_surface(arr: np.ndarray, upscale: int = 1, into=None):
	if upscale > 1:
		arr = _upscale(arr, upscale)

	arr = arr.swapaxes(1,0)

	if into is None:
		return pygame.surfarray.make_surface(arr)
	else:
		pygame.pixelcopy.array_to_surface(into, arr)
		return into


def draw_rectangle(arr: np.ndarray, color, x, y, w, h) -> None:
	arr[y        , x : x + w - 1, ...] = color
	arr[y + h - 1, x : x + w - 1, ...] = color
	arr[y : y + h - 1, x        , ...] = color
	arr[y : y + h - 1, x + w - 1, ...] = color


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


def chr_to_stacked(rom_chr: bytes) -> np.ndarray:
	"""
	:returns CHR as array (2-bit), shape (512, 8, 8)
	"""
	# TODO optimization: I suspect (512, 8, 8) is faster than (8, 8, 512), but confirm (try both and compare performance)
	return chr_to_array(rom_chr, width=1).reshape((512, 8, 8))


def load_palette_file(path: Path | str) -> np.ndarray:
	data = Path(path).read_bytes()

	# TODO: include emphasis bits (data past 192)

	if True:
		# Fast numpy code
		palette = np.frombuffer(data[:192], dtype=np.uint8).reshape((64, 3))
	else:
		# Slow iterative code
		palette = np.empty((64, 3), dtype=np.uint8)
		for idx in range(64):
			palette[idx, 0] = data[3 * idx]
			palette[idx, 1] = data[3 * idx + 1]
			palette[idx, 2] = data[3 * idx + 2]

	return palette
