#!/usr/bin/env python3

from dataclasses import dataclass
import logging
from pathlib import Path
from os import PathLike


@dataclass
class INesHeader:
	# TODO: other parameters that are commented out

	prg_rom_size_16kb_chunks: int
	chr_rom_size_8kb_chunks: int

	vertical_mirroring: bool
	battery_ram: bool
	trainer: bool
	# alt_nametable_layout: bool
	# vs_unisystem: bool
	# playchoice10: bool

	# ines2: bool

	mapper: int
	submapper: int
	
	# prg_ram_size_shift_count: int
	# prg_nvram_size_shift_count: int

	# cpu_ppu_timing_mode: int

	@classmethod
	def from_data(cls, data: bytes):

		magic = data[:4]

		if magic != b'NES\x1a':
			raise ValueError(f'Invalid INES header - first 4 bytes {magic}')

		prg_rom_size_16kb_chunks = data[4]
		chr_rom_size_8kb_chunks = data[5]

		mapper = (data[7] & 0xF0) | ((data[6] & 0xF0) >> 4)

		ines2 = ((data[7] & 0b00001100) >> 2) == 0b10

		submapper = 0

		if ines2:
			mapper += (data[8] & 0x0F) << 8
			submapper = (data[8] & 0xF0) >> 4
			prg_rom_size_16kb_chunks += (data[9] & 0x0F) << 8
			chr_rom_size_8kb_chunks += (data[9] & 0xF0) << 4

		return cls(
			prg_rom_size_16kb_chunks=prg_rom_size_16kb_chunks,
			chr_rom_size_8kb_chunks=chr_rom_size_8kb_chunks,
			vertical_mirroring=bool(data[6] & 0x01),
			battery_ram=bool(data[6] & 0x02),
			mapper=mapper,
			submapper=submapper,
			trainer=bool(data[6] & 0x04),
		)


class Rom:
	def __init__(self, path: Path | PathLike | str):

		self.header = None
		self.trainer = None
		self.prg = None
		self.chr = None

		path = Path(path)
		data = path.read_bytes()

		self.header = INesHeader.from_data(data[:16])
		data = data[16:]

		logging.info(f'Mapper: {self.header.mapper}')

		if self.header.trainer:
			logging.info('ROM has trainer')
			self.trainer = data[:512]
			data = data[512:]

		prg_length = self.header.prg_rom_size_16kb_chunks * 16384
		chr_length = self.header.chr_rom_size_8kb_chunks * 8192

		logging.info(f'PRG ROM size: {prg_length // 1024} kiB')
		logging.info(f'CHR ROM size: {chr_length // 1024} kiB')

		if len(data) != prg_length + chr_length:
			raise ValueError(f'Invalid ROM data section length - expected {prg_length + chr_length}, actual {len(data)}')

		self.prg = data[:prg_length]
		self.chr = data[prg_length:]
		assert len(self.chr) == chr_length
